#!/usr/bin/env python3
"""
シフトスケジューリングと残業時間最適化ソルバー
----------------------------------------
機能:
1. シフトスケジューリング (OR-Tools CP-SAT使用)
   - 必要人数の充足
   - 従業員の勤務可能日の考慮
   - 連続勤務制限
   - 総人件費の最小化

2. 残業時間の最適配分 (HiGHS LP使用)
   - 必要残業時間の割り当て
   - 個人別の上限考慮
   - 総コストの最小化

使用方法:
    python solve.py demo_input.json > solution.json
"""
import json, sys, math
from ortools.sat.python import cp_model         # CP-SAT用
from ortools.linear_solver import pywraplp      # HiGHS LP用

def _create_highs_solver(model_name="model"):
    """
    HiGHSソルバーの生成（OR-Toolsバージョン差異を吸収）
    
    Args:
        model_name: ソルバーモデルの名前
    Returns:
        設定済みHiGHSソルバーインスタンス
    """
    try:
        # OR-Tools v9.9以降用
        return pywraplp.Solver.CreateSolver("HIGHS", model_name)
    except TypeError:
        # OR-Tools v9.8以前用
        s = pywraplp.Solver.CreateSolver("HIGHS")
        s.SetSolverSpecificParametersAsString(f"ModelName={model_name}")
        return s

# ---------- 1. シフトスケジューリング (CP-SAT) ----------
def solve_schedule(data):
    # 入力データの準備
    days = data['days']                    # 営業日リスト
    D = range(len(days))                   # 日数分の範囲
    employees = data['employees']          # 従業員リスト
    W = range(len(employees))              # 従業員数分の範囲
    req = data['shift_requirements']       # 各日の必要人数
    max_consec = data.get('max_consecutive', 5)  # 連続勤務上限（デフォルト5日）

    # CP-SATモデルの構築
    model = cp_model.CpModel()
    
    # 決定変数: x[w,d] = 従業員wが日dに勤務するか（1=する、0=しない）
    x = {(w,d): model.NewBoolVar(f'x_{w}_{d}') for w in W for d in D}

    # ハード制約1: 必要人数の充足
    # 各日の勤務者数が必要人数と一致すること
    for d in D:
        model.Add(sum(x[w,d] for w in W) == req[d])

    # ハード制約2: 勤務可能日と最大シフト数
    for w, emp in enumerate(employees):
        # 勤務不可能な日には入れない
        for d in D:
            if emp['availability'][d] == 0:  # 0=勤務不可
                model.Add(x[w,d] == 0)
                
        # 最大シフト数の制限（指定がない場合は全日数）
        max_shifts = emp.get('max_shifts', len(days))
        model.Add(sum(x[w,d] for d in D) <= max_shifts)

        # ハード制約3: 連続勤務日数の制限
        # 任意の連続した日数で上限を超えないようにする
        for start in range(len(days) - max_consec):
            model.Add(sum(x[w,d] for d in range(start, start+max_consec+1)) <= max_consec)

    # 目的関数: 総人件費の最小化
    # 各従業員のコスト × その従業員の勤務日数 の合計
    objective = []
    for w, emp in enumerate(employees):
        cost = emp.get('cost', 100)  # コスト指定がない場合は100
        objective.extend(cost * x[w,d] for d in D)
    model.Minimize(sum(objective))

    # ソルバーの設定と実行
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = data.get('time_limit_sec', 30)  # 制限時間
    status = solver.Solve(model)

    # 解が見つからなかった場合
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {'status': 'INFEASIBLE'}

    # 結果の整形
    schedule = []
    for w, emp in enumerate(employees):
        shifts = [ int(solver.Value(x[w,d])) for d in D ]  # 各日の勤務有無（0/1）
        schedule.append({'id': emp['id'], 'shifts': shifts})
    
    return {
        'status': 'OK',
        'objective': solver.ObjectiveValue(),    # 最適化された総コスト
        'wall_time_sec': solver.WallTime(),      # 計算時間
        'schedule': schedule                      # シフト表
    }

# ---------- 2. 残業時間最適配分 (LP) ----------
def solve_overtime_lp(data):
    # 入力データの準備
    employees = data['employees']          # 従業員リスト
    total_ot = data['total_overtime_hours']  # 必要な総残業時間

    # HiGHSソルバーの初期化
    solver = _create_highs_solver("overtime_lp")

    # 決定変数: 各従業員の残業時間（0～個人別上限の範囲で）
    x = {i: solver.NumVar(0, emp['max_overtime'], f'ot_{i}')
         for i, emp in enumerate(employees)}

    # 制約: 総残業時間の充足
    solver.Add(sum(x.values()) == total_ot)
    
    # 目的関数: 残業コストの最小化
    solver.Minimize(sum(emp['overtime_cost'] * x[i]
                       for i, emp in enumerate(employees)))

    # ソルバー実行
    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return {'status': 'INFEASIBLE'}

    # 結果の整形
    return {
        'status': 'OK',
        'objective': solver.Objective().Value(),
        'allocation': [
            {'id': emp['id'], 'overtime_hours': x[i].solution_value()}
            for i, emp in enumerate(employees)
        ]
    }

# ---------- メイン処理 ----------
def main():
    # コマンドライン引数のチェック
    if len(sys.argv) < 2:
        print('使用方法: solve.py <input.json>', file=sys.stderr)
        sys.exit(1)
    
    # 入力JSONの読み込み
    with open(sys.argv[1], encoding='utf-8') as f:
        js = json.load(f)

    # 各ソルバーの実行
    result = {}
    if 'schedule' in js:
        result['schedule_result'] = solve_schedule(js['schedule'])
    if 'overtime_lp' in js:
        result['overtime_result'] = solve_overtime_lp(js['overtime_lp'])

    # 結果のJSON出力（日本語対応）
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()