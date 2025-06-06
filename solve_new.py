#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高度な従業員シフトスケジューリングおよび残業時間最適化ソルバー
----------------------------------------------------------------
機能:
1. シフトスケジューリング (OR-Tools CP-SAT使用)
   - 複数施設対応 (各施設・各時間帯に最低1名配置)
   - 24時間対応
   - 特定時間帯の清掃シフト要員計算 (タスク量に基づく)
   - 従業員の詳細な勤務可能時間（曜日・時間指定）の考慮
   - 従業員の希望勤務施設の考慮
   - (ソフト制約として) 契約上の週最大勤務日数および1日最大勤務時間の遵守試行
   - (ソフト制約として) 連続勤務日数の制限試行
   - 総人件費とペナルティコストの最小化

2. 残業時間の最適配分 (HiGHS LP使用)
   - 必要残業時間の割り当て
   - 個人別の上限考慮
   - 総残業コストの最小化

local_main 実行方法:
    python solve_new.py generated_combined_input_data.json > solution.json
    ターミナルに直接表示されます（標準エラー出力なので）。もしファイルに保存したい場合は、
    python solve_new.py generated_combined_input_data.json > solution.json 2> run_debug.log

"""
import json
import sys
import math
import datetime
import functions_framework # Cloud Run/Functions 用
from ortools.sat.python import cp_model
from ortools.linear_solver import pywraplp

# --- グローバル定数 ---
HOURS_IN_DAY = 24
MAX_RETRY_ATTEMPTS = 3 # ソフト制約緩和の最大試行回数
PENALTY_REDUCTION_FACTOR = 0.5 # ペナルティを緩和する際の係数
DEFAULT_TIME_LIMIT_SEC = 60 # Cloud Run 用のデフォルト実行時間制限

_local_full_result_for_testing_only = {
    'logs': {
        'schedule': [],
        'overtime': [],
        'errors': [],
        'warnings': [],
        'info': []
    },
    'schedule_result': None,
    'overtime_result': None,
    'applied_constraints_history': []
}
CP_SOLVER_STATUS_MAP = {
    cp_model.OPTIMAL: 'OPTIMAL',
    cp_model.FEASIBLE: 'FEASIBLE',
    cp_model.INFEASIBLE: 'INFEASIBLE',
    cp_model.MODEL_INVALID: 'MODEL_INVALID',
    cp_model.UNKNOWN: 'UNKNOWN'
}

# --- HiGHSソルバー生成ユーティリティ ---
def _create_highs_solver(model_name="model"):
    try:
        return pywraplp.Solver.CreateSolver("HIGHS", model_name)
    except TypeError:
        s = pywraplp.Solver.CreateSolver("HIGHS")
        s.SetSolverSpecificParametersAsString(f"ModelName={model_name}")
        return s

# --- ログ関連ヘルパー関数 ---
def add_log(full_result_ref, category, message, details=None):
    """汎用ログ追加関数"""
    return
    # log_entry = {"timestamp": datetime.datetime.now().isoformat(), "message": message}
    # if details:
    #     log_entry["details"] = details
    
    # # HTTP関数の場合、最初に初期化されることを想定。ローカルでは事前に初期化済み。
    # if 'logs' not in full_result_ref: 
    #     full_result_ref['logs'] = {'schedule': [], 'overtime': [], 'errors': [], 'warnings': [], 'info': []}
    
    # if category in full_result_ref['logs']:
    #     full_result_ref['logs'][category].append(log_entry)
    # else:
    #     error_log_entry = {
    #         "timestamp": datetime.datetime.now().isoformat(),
    #         "message": f"未知のログカテゴリ: {category}",
    #         "original_message": message
    #     }
    #     if details: error_log_entry["original_details"] = details
    #     # 未知のカテゴリもエラーログに記録する
    #     if 'errors' not in full_result_ref['logs']: # errorsキーがない場合も考慮
    #          full_result_ref['logs']['errors'] = []
    #     full_result_ref['logs']['errors'].append(error_log_entry)
    #     # 標準エラーにも警告を出すのは良いプラクティス
    #     print(f"警告(ログ): 未知のログカテゴリ '{category}' ({message}) が使用されました。", file=sys.stderr)

def add_model_stats_log(full_result_ref, model_instance, category, event_message):
    """モデルの統計情報をログに記録するヘルパー関数"""
    return
    # stats = {'num_variables': 'unknown', 'num_constraints': 'unknown'}
    # model_type_str = str(type(model_instance))
    # log_details_base = {"event": event_message, "model_type": model_type_str}
    # try:
    #     if isinstance(model_instance, cp_model.CpModel):
    #         proto = model_instance.Proto()
    #         stats['num_variables'] = len(proto.variables)
    #         stats['num_constraints'] = len(proto.constraints)
    #         model_type_str = "CpModel"
    #     elif hasattr(model_instance, 'NumVariables') and hasattr(model_instance, 'NumConstraints'):
    #         stats['num_variables'] = model_instance.NumVariables()
    #         stats['num_constraints'] = model_instance.NumConstraints()
    #         model_type_str = "LpSolver"
    #     else:
    #         add_log('warnings', f'モデル統計情報を取得できませんでした: 未知のモデルタイプ {model_type_str}', {**log_details_base, "error_details": "Unknown model type for stats."})
    #         return
    #     log_details = {**log_details_base, "model_type": model_type_str, **stats}
    #     log_message = f"{event_message} - モデル統計: 変数={stats['num_variables']}, 制約={stats['num_constraints']}"
    #     add_log(category, log_message, log_details)
    # except Exception as e:
    #     add_log('errors', f'モデル統計情報の取得中に予期せぬエラー: {str(e)}', {**log_details_base, "error_details": str(e)})

# --- その他ヘルパー関数 (full_result_ref を受け取るように変更) ---
def parse_time_to_int(full_result_ref, time_str): # full_result_ref を追加
    try:
        return int(time_str.split(":")[0])
    except (ValueError, AttributeError, IndexError) as e:
        add_log(full_result_ref, 'errors', f"時間文字列 '{time_str}' のパースに失敗: {e}")
        raise ValueError(f"無効な時間形式: {time_str}") from e

def get_employee_availability_matrix(full_result_ref, employees_data, num_total_days, days_of_week_order, planning_start_date_obj): # full_result_ref を追加
    availability_matrix = {}
    for emp_idx, emp in enumerate(employees_data):
        for avail_slot in emp.get('availability', []):
            try:
                day_of_week_spec = avail_slot['day_of_week']
                start_hour_int = parse_time_to_int(full_result_ref, avail_slot['start_time']) # full_result_ref を渡す
                end_hour_int = parse_time_to_int(full_result_ref, avail_slot['end_time'])   # full_result_ref を渡す
                for day_idx in range(num_total_days):
                    current_date = planning_start_date_obj + datetime.timedelta(days=day_idx)
                    current_day_of_week_str = days_of_week_order[current_date.weekday()]
                    if current_day_of_week_str == day_of_week_spec:
                        for hour_idx in range(start_hour_int, end_hour_int):
                            if 0 <= hour_idx < HOURS_IN_DAY:
                                availability_matrix[(emp_idx, day_idx, hour_idx)] = True
            except KeyError as e: add_log(full_result_ref, 'warnings', f"従業員 {emp.get('id', 'N/A')} の勤務可能時間データにキーエラー: {e}", {"employee_id": emp.get('id')})
            except ValueError as e: add_log(full_result_ref, 'warnings', f"従業員 {emp.get('id', 'N/A')} の時間関連データエラー: {e}", {"employee_id": emp.get('id')})
    return availability_matrix

def get_cleaning_tasks_for_day_facility(full_result_ref, facility_id_str, current_date_obj, cleaning_data_json, days_of_week_order): # full_result_ref を追加
    date_str = current_date_obj.strftime("%Y-%m-%d")
    day_of_week_str = days_of_week_order[current_date_obj.weekday()]
    try:
        facility_tasks = cleaning_data_json.get(facility_id_str, {})
        day_specific_tasks = facility_tasks.get(day_of_week_str, {})
        if date_str in day_specific_tasks: return day_specific_tasks[date_str]
        default_tasks = facility_tasks.get("default_tasks_for_day_of_week", {})
        if day_of_week_str in default_tasks: return default_tasks[day_of_week_str]
    except Exception as e: add_log(full_result_ref, 'warnings', f"清掃タスク取得中にエラー ({facility_id_str}, {date_str}): {e}", {"facility_id": facility_id_str, "date": date_str})
    return 0

# ---------- 1. シフトスケジューリング (CP-SAT) ----------
def solve_schedule(full_result_ref, schedule_input_data, cleaning_tasks_data, time_limit_sec, retry_attempt=0, penalty_multipliers=None):
    """
    シフトスケジューリングを行う関数 (ソフト制約緩和による再試行ロジックを含む)
    """
    run_id = f"attempt_{retry_attempt}_{datetime.datetime.now().strftime('%H%M%S%f')}"
    add_log(full_result_ref, 'info', f"[{run_id}] シフトスケジューリング処理開始 (試行回数: {retry_attempt})", {"penalty_multipliers": penalty_multipliers})
    
    if penalty_multipliers is None:
        penalty_multipliers = {
            "consecutive_days": 1.0, "weekly_days": 1.0, "daily_hours": 1.0, "staff_shortage": 1.0
        }

    settings = schedule_input_data['settings']
    facilities_data = schedule_input_data['facilities']
    employees_data = schedule_input_data['employees']

    num_facilities = len(facilities_data)
    F_indices = range(num_facilities)
    facility_id_to_idx = {f['id']: i for i, f in enumerate(facilities_data)}
    facility_idx_to_id = {i: f['id'] for i, f in enumerate(facilities_data)}
    num_employees = len(employees_data)
    W_indices = range(num_employees)
    employee_id_to_idx = {e['id']: i for i, e in enumerate(employees_data)}
    employee_idx_to_id = {i: e['id'] for i, e in enumerate(employees_data)}

    planning_start_date_obj = datetime.datetime.strptime(settings['planning_start_date'], "%Y-%m-%d").date()
    num_total_days = settings['num_days_in_planning_period']
    D_indices = range(num_total_days)
    days_of_week_order = settings.get('days_of_week_order', ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    H_indices = range(HOURS_IN_DAY)
    cleaning_start_h = settings['cleaning_shift_start_hour']
    cleaning_end_h = settings['cleaning_shift_end_hour'] 
    cleaning_hours_duration = cleaning_end_h - cleaning_start_h
    
    emp_avail_matrix = get_employee_availability_matrix(full_result_ref, employees_data, num_total_days, days_of_week_order, planning_start_date_obj)
    add_log(full_result_ref, 'info', f"[{run_id}] 従業員の勤務可能時間マトリックス作成完了")

    emp_preferred_facilities_idx_sets = [
        set(facility_id_to_idx[fid] for fid in emp.get('preferred_facilities', []) if fid in facility_id_to_idx)
        for emp in employees_data
    ]

    model = cp_model.CpModel()
    add_log(full_result_ref, 'schedule', f"[{run_id}] CP-SATモデルオブジェクト作成完了")

    x = {}
    for f_idx in F_indices:
        for w_idx in W_indices:
            for d_idx in D_indices:
                for h_idx in H_indices:
                    x[f_idx, w_idx, d_idx, h_idx] = model.NewBoolVar(f'x_f{f_idx}_w{w_idx}_d{d_idx}_h{h_idx}')
    add_log(full_result_ref, 'schedule', f"[{run_id}] 決定変数 (x) 作成完了", {"num_x_vars": len(x)})

    works_on_day = {}
    for w_idx in W_indices:
        for d_idx in D_indices:
            works_on_day[w_idx, d_idx] = model.NewBoolVar(f'works_w{w_idx}_d{d_idx}')
    add_log(full_result_ref, 'schedule', f"[{run_id}] 補助変数 (works_on_day) 作成完了", {"num_works_on_day_vars": len(works_on_day)})

    # --- 制約設定の記録用 ---
    current_constraints_settings = {
        "run_id": run_id,
        "retry_attempt": retry_attempt,
        "hard_constraints": [
            "employee_availability_and_preferred_facility",
            "employee_one_facility_at_a_time",
            "works_on_day_definition"
        ],
        "soft_constraints_settings": {
            "consecutive_days": {
                "base_penalty": settings.get('consecutive_days_penalty', 20000),
                "multiplier": penalty_multipliers.get("consecutive_days", 1.0)
            },
            "weekly_days": {
                "base_penalty": settings.get('weekly_days_penalty', 10000),
                "multiplier": penalty_multipliers.get("weekly_days", 1.0)
            },
            "daily_hours": {
                "base_penalty": settings.get('daily_hours_penalty', 30000),
                "multiplier": penalty_multipliers.get("daily_hours", 1.0)
            },
            "staff_shortage": {
                "base_penalty": settings.get('staff_shortage_penalty', 50000),
                "multiplier": penalty_multipliers.get("staff_shortage", 1.0)
            }
        }
    }
    if 'applied_constraints_history' not in full_result_ref: 
        full_result_ref['applied_constraints_history'] = [] # HTTP関数の場合、最初に初期化
    full_result_ref['applied_constraints_history'].append(current_constraints_settings)


    # --- ハード制約 ---
    add_log(full_result_ref, 'schedule', f"[{run_id}] ハード制約の追加開始")
    # 1. 従業員の勤務可能時間と希望施設
    for f_idx in F_indices:
        for w_idx in W_indices:
            if emp_preferred_facilities_idx_sets[w_idx] and f_idx not in emp_preferred_facilities_idx_sets[w_idx]:
                 for d_idx in D_indices:
                    for h_idx in H_indices: model.Add(x[f_idx, w_idx, d_idx, h_idx] == 0)
                    # continue # この continue は不要。内側のループで処理が終わる。
            for d_idx in D_indices:
                for h_idx in H_indices:
                    if not emp_avail_matrix.get((w_idx, d_idx, h_idx), False):
                        model.Add(x[f_idx, w_idx, d_idx, h_idx] == 0)
    
    # 2. 従業員は同時に1つの施設でのみ勤務可能
    for w_idx in W_indices:
        for d_idx in D_indices:
            for h_idx in H_indices:
                model.Add(sum(x[f_idx, w_idx, d_idx, h_idx] for f_idx in F_indices) <= 1)

    # 3. works_on_day 変数の設定
    for w_idx in W_indices:
        for d_idx in D_indices:
            hours_worked_this_day = sum(x[f_idx, w_idx, d_idx, h_idx] for f_idx in F_indices for h_idx in H_indices)
            model.Add(hours_worked_this_day > 0).OnlyEnforceIf(works_on_day[w_idx, d_idx])
            model.Add(hours_worked_this_day == 0).OnlyEnforceIf(works_on_day[w_idx, d_idx].Not())
    
    add_log(full_result_ref, 'schedule', f"[{run_id}] 全てのハード制約の追加完了")
    add_model_stats_log(full_result_ref, model, 'schedule', f"[{run_id}] ハード制約追加後のモデル状態")

    # --- ソフト制約 ---
    soft_penalty_terms = []
    objective_terms = []
    
    # 〇 最大連続勤務日数 (ソフト制約)
    max_consecutive_setting = settings.get('max_consecutive_work_days', 5)
    base_consecutive_penalty = current_constraints_settings["soft_constraints_settings"]["consecutive_days"]["base_penalty"]
    current_consecutive_penalty = base_consecutive_penalty * current_constraints_settings["soft_constraints_settings"]["consecutive_days"]["multiplier"]

    if max_consecutive_setting > 0 and num_total_days > max_consecutive_setting:
        for w_idx in W_indices:
            for d_idx_start in range(num_total_days - max_consecutive_setting):
                consecutive_days_worked = sum(works_on_day[w_idx, d] for d in range(d_idx_start, d_idx_start + max_consecutive_setting + 1))
                excess_consecutive = model.NewIntVar(0, max_consecutive_setting + 2, f'ex_consec_w{w_idx}_d{d_idx_start}') # 上限を少し余裕持たせる
                
                is_exceeding = model.NewBoolVar(f'is_ex_consec_w{w_idx}_d{d_idx_start}')
                model.Add(consecutive_days_worked > max_consecutive_setting).OnlyEnforceIf(is_exceeding)
                model.Add(consecutive_days_worked <= max_consecutive_setting).OnlyEnforceIf(is_exceeding.Not())
                model.Add(excess_consecutive == consecutive_days_worked - max_consecutive_setting).OnlyEnforceIf(is_exceeding)
                model.Add(excess_consecutive == 0).OnlyEnforceIf(is_exceeding.Not())
                soft_penalty_terms.append(excess_consecutive * current_consecutive_penalty)

    # 〇 週あたりの最大労働日数 (ソフト制約)
    base_weekly_days_penalty = current_constraints_settings["soft_constraints_settings"]["weekly_days"]["base_penalty"]
    current_weekly_days_penalty = base_weekly_days_penalty * current_constraints_settings["soft_constraints_settings"]["weekly_days"]["multiplier"]
    for w_idx in W_indices:
        max_days_week = employees_data[w_idx].get('contract_max_days_per_week', 7)
        for week_start_day_idx in range(0, num_total_days, 7):
            days_in_week = sum(works_on_day[w_idx, d_idx] for d_idx in range(week_start_day_idx, min(week_start_day_idx + 7, num_total_days)))
            excess_weekly_days = model.NewIntVar(0, 8, f'ex_week_w{w_idx}_wk{week_start_day_idx}') # 上限
            
            is_exceeding = model.NewBoolVar(f'is_ex_week_w{w_idx}_wk{week_start_day_idx}')
            model.Add(days_in_week > max_days_week).OnlyEnforceIf(is_exceeding)
            model.Add(days_in_week <= max_days_week).OnlyEnforceIf(is_exceeding.Not())
            model.Add(excess_weekly_days == days_in_week - max_days_week).OnlyEnforceIf(is_exceeding)
            model.Add(excess_weekly_days == 0).OnlyEnforceIf(is_exceeding.Not())
            soft_penalty_terms.append(excess_weekly_days * current_weekly_days_penalty)

    # 〇 1日あたりの最大労働時間 (ソフト制約)
    base_daily_hours_penalty = current_constraints_settings["soft_constraints_settings"]["daily_hours"]["base_penalty"]
    current_daily_hours_penalty = base_daily_hours_penalty * current_constraints_settings["soft_constraints_settings"]["daily_hours"]["multiplier"]
    for w_idx in W_indices:
        max_hours_day = employees_data[w_idx].get('contract_max_hours_per_day', HOURS_IN_DAY)
        for d_idx in D_indices:
            hours_worked = sum(x[f_idx, w_idx, d_idx, h_idx] for f_idx in F_indices for h_idx in H_indices)
            excess_daily_hours = model.NewIntVar(0, HOURS_IN_DAY + 1, f'ex_day_w{w_idx}_d{d_idx}') # 上限
            
            is_exceeding = model.NewBoolVar(f'is_ex_day_w{w_idx}_d{d_idx}')
            model.Add(hours_worked > max_hours_day).OnlyEnforceIf(is_exceeding)
            model.Add(hours_worked <= max_hours_day).OnlyEnforceIf(is_exceeding.Not())
            model.Add(excess_daily_hours == hours_worked - max_hours_day).OnlyEnforceIf(is_exceeding)
            model.Add(excess_daily_hours == 0).OnlyEnforceIf(is_exceeding.Not())
            soft_penalty_terms.append(excess_daily_hours * current_daily_hours_penalty)

    # 〇 各日の必要人数の充足 (ソフト制約)
    base_staff_shortage_penalty = current_constraints_settings["soft_constraints_settings"]["staff_shortage"]["base_penalty"]
    current_staff_shortage_penalty = base_staff_shortage_penalty * current_constraints_settings["soft_constraints_settings"]["staff_shortage"]["multiplier"]
    for f_idx in F_indices:
        facility_details = facilities_data[f_idx]
        facility_cleaning_capacity_per_hr = facility_details.get('cleaning_capacity_tasks_per_hour_per_employee', 1)
        if facility_cleaning_capacity_per_hr <= 0: facility_cleaning_capacity_per_hr = 1
        for d_idx in D_indices:
            current_date = planning_start_date_obj + datetime.timedelta(days=d_idx)
            daily_cleaning_tasks = get_cleaning_tasks_for_day_facility(full_result_ref, facility_idx_to_id[f_idx], current_date, cleaning_tasks_data, days_of_week_order)
            for h_idx in H_indices:
                required_staff_target = 1
                if cleaning_start_h <= h_idx < cleaning_end_h:
                    if cleaning_hours_duration > 0 and daily_cleaning_tasks > 0:
                        required_staff_target = max(1, math.ceil(daily_cleaning_tasks / (facility_cleaning_capacity_per_hr * cleaning_hours_duration)))
                    else: required_staff_target = 1
                
                staff_count = sum(x[f_idx, w_idx, d_idx, h_idx] for w_idx in W_indices)
                actual_shortage = model.NewIntVar(0, max(1,num_employees), f'short_f{f_idx}_d{d_idx}_h{h_idx}') # 上限は従業員数
                
                is_short = model.NewBoolVar(f'is_short_f{f_idx}_d{d_idx}_h{h_idx}')
                model.Add(staff_count < required_staff_target).OnlyEnforceIf(is_short)
                model.Add(staff_count >= required_staff_target).OnlyEnforceIf(is_short.Not())
                model.Add(actual_shortage == required_staff_target - staff_count).OnlyEnforceIf(is_short)
                model.Add(actual_shortage == 0).OnlyEnforceIf(is_short.Not())
                soft_penalty_terms.append(actual_shortage * current_staff_shortage_penalty)

    # 〇 総人件費の最小化 (目的関数の一部)
    for f_idx in F_indices:
        for w_idx in W_indices:
            cost_per_hour = employees_data[w_idx].get('cost_per_hour', 1000)
            for d_idx in D_indices:
                for h_idx in H_indices:
                    objective_terms.append(x[f_idx, w_idx, d_idx, h_idx] * cost_per_hour)
    
    model.Minimize(sum(objective_terms) + sum(soft_penalty_terms))
    add_log(full_result_ref, 'schedule', f"[{run_id}] 目的関数設定完了")
    add_model_stats_log(full_result_ref, model, 'schedule', f"[{run_id}] 目的関数設定後のモデル状態")
    
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = settings.get('time_limit_sec', 60)
    solver.parameters.log_search_progress = True
    # solver.parameters.num_search_workers = 8 # 必要に応じて有効化

    add_log(full_result_ref, 'info', f"[{run_id}] CP-SATソルバー実行開始 (制限時間: {time_limit_sec}秒)")
    status = solver.Solve(model)
    status_str = CP_SOLVER_STATUS_MAP.get(status, 'UNKNOWN')
    objective_value = solver.ObjectiveValue() if status in [cp_model.OPTIMAL, cp_model.FEASIBLE] else None
    wall_time = solver.WallTime()
    add_log(full_result_ref, 'info', f"[{run_id}] CP-SATソルバー実行完了", {'status': status_str, 'wall_time': wall_time, 'objective': objective_value})

    result = {'status': status_str, 'run_id': run_id, 'applied_constraints_settings': current_constraints_settings}
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        result['objective'] = objective_value
        result['wall_time_sec'] = wall_time
        add_log(full_result_ref, 'schedule', f"[{run_id}] 解が見つかりました", {"objective": result['objective'], "wall_time_sec": result['wall_time_sec']})
        
        assignments = []
        for w_idx in W_indices:
            emp_id = employee_idx_to_id[w_idx]
            for d_idx in D_indices:
                current_date_str = (planning_start_date_obj + datetime.timedelta(days=d_idx)).strftime("%Y-%m-%d")
                for f_idx in F_indices:
                    facility_id = facility_idx_to_id[f_idx]
                    current_block_start_hour = -1
                    for h_idx in H_indices:
                        if solver.Value(x[f_idx, w_idx, d_idx, h_idx]) == 1:
                            if current_block_start_hour == -1: current_block_start_hour = h_idx
                        else:
                            if current_block_start_hour != -1:
                                assignments.append({"employee_id": emp_id, "facility_id": facility_id, "date": current_date_str, "start_hour": current_block_start_hour, "end_hour": h_idx})
                                current_block_start_hour = -1
                    if current_block_start_hour != -1:
                        assignments.append({"employee_id": emp_id, "facility_id": facility_id, "date": current_date_str, "start_hour": current_block_start_hour, "end_hour": HOURS_IN_DAY})
        result['assignments'] = assignments

        diagnostics = {"hours_worked_per_employee": {}, "days_worked_per_employee": {}}
        for w_idx in W_indices:
            emp_id = employee_idx_to_id[w_idx]
            total_hours = sum(solver.Value(x[f_idx, w_idx, d_idx, h_idx]) for f_idx in F_indices for d_idx in D_indices for h_idx in H_indices)
            diagnostics["hours_worked_per_employee"][emp_id] = total_hours
            total_days = sum(solver.Value(works_on_day[w_idx, d_idx]) for d_idx in D_indices)
            diagnostics["days_worked_per_employee"][emp_id] = total_days
        result["diagnostics"] = diagnostics
        add_log(full_result_ref, 'schedule', f"[{run_id}] 結果の整形完了", {"num_assignments": len(assignments)})
        return result # 成功したので結果を返す
    else: # INFEASIBLE, MODEL_INVALID, UNKNOWN
        result['message'] = f"[{run_id}] 解が見つかりませんでした (ステータス: {status_str})"
        add_log(full_result_ref, 'errors', result['message'], {"status_code": status, "status_text": status_str})

        if status == cp_model.INFEASIBLE and retry_attempt < MAX_RETRY_ATTEMPTS:
            add_log(full_result_ref, 'warnings', f"[{run_id}] 実行不可能でした。ペナルティを緩和して再試行します (試行 {retry_attempt + 1}/{MAX_RETRY_ATTEMPTS})。")
            new_penalty_multipliers = {k: v * PENALTY_REDUCTION_FACTOR for k, v in penalty_multipliers.items()}
            return solve_schedule(schedule_input_data, cleaning_tasks_data, retry_attempt + 1, new_penalty_multipliers)
        else:
            if status == cp_model.INFEASIBLE:
                add_log(full_result_ref, 'errors', f"[{run_id}] 最大試行回数 ({MAX_RETRY_ATTEMPTS}) に達しても実行不可能なままでした。")
            return result # 最終的な失敗結果を返す

# ---------- 2. 残業時間最適配分 (LP) ----------
def solve_overtime_lp(full_result_ref, overtime_input_data):
    run_id = f"overtime_{datetime.datetime.now().strftime('%H%M%S%f')}"
    add_log(full_result_ref, 'info', f"[{run_id}] 残業時間最適配分処理開始")
    if not overtime_input_data or not overtime_input_data.get('employees'):
        msg = '残業データが提供されていないか、従業員リストが空です。'
        add_log(full_result_ref, 'warnings', f"[{run_id}] {msg}")
        return {'status': 'NO_DATA', 'message': msg, 'run_id': run_id}

    employees_ot_data = overtime_input_data['employees']
    total_ot_needed = overtime_input_data.get('total_overtime_hours', 0)

    if total_ot_needed <= 0:
        msg = '必要な総残業時間が0以下です。処理をスキップします。'
        add_log(full_result_ref, 'info', f"[{run_id}] {msg}")
        return {'status': 'OK', 'objective': 0, 'allocation': [], 'message': msg, 'run_id': run_id}

    solver = _create_highs_solver("overtime_lp")
    if not solver:
        msg = 'HiGHSソルバーの作成に失敗しました。'
        add_log(full_result_ref, 'errors', f"[{run_id}] {msg}")
        return {'status': 'SOLVER_ERROR', 'message': msg, 'run_id': run_id}
    add_log(full_result_ref, 'overtime', f"[{run_id}] HiGHSソルバーオブジェクト作成完了")

    x = {}
    for emp in employees_ot_data:
        max_ot = emp.get('max_overtime', 0)
        if 'id' not in emp or max_ot <= 0:
            add_log(full_result_ref, 'warnings', f"[{run_id}] 従業員 {emp.get('id', 'ID不明')} の残業変数は作成されません。", emp)
            continue
        x[emp['id']] = solver.NumVar(0, max_ot, f'ot_{emp["id"]}')
    
    if not x:
        if total_ot_needed > 0: msg = "残業を割り当てる有効な従業員がいませんが、残業が必要です。"
        else: msg = "残業を割り当てる有効な従業員がおらず、必要な残業もありません。"
        log_level = 'errors' if total_ot_needed > 0 else 'info'
        add_log(full_result_ref, log_level, f"[{run_id}] {msg}")
        return {'status': 'INFEASIBLE' if total_ot_needed > 0 else 'OK', 'objective': 0, 'allocation': [], 'message': msg, 'run_id': run_id}
            
    add_log(full_result_ref, 'overtime', f"[{run_id}] 決定変数作成完了 (有効従業員数: {len(x)})")
    solver.Add(sum(x.values()) == total_ot_needed)
    add_log(full_result_ref, 'overtime', f"[{run_id}] 総残業時間制約 ({total_ot_needed}時間) 追加完了")
    
    objective_terms = [emp.get('overtime_cost', 99999) * x[emp['id']] for emp in employees_ot_data if emp['id'] in x]
    if objective_terms: solver.Minimize(sum(objective_terms)); add_log(full_result_ref, 'overtime', f"[{run_id}] 目的関数設定完了")
    else: add_log(full_result_ref, 'warnings', f"[{run_id}] 残業配分: 目的関数が設定されませんでした。")

    add_model_stats_log(full_result_ref, solver, 'overtime', f"[{run_id}] LPモデル構築完了後の状態")
    add_log(full_result_ref, 'info', f"[{run_id}] LPソルバー実行開始")
    status = solver.Solve()
    add_log(full_result_ref, 'info', f"[{run_id}] LPソルバー実行完了 (ステータスコード: {status})")

    if status == pywraplp.Solver.OPTIMAL or status == pywraplp.Solver.FEASIBLE:
        obj_val = solver.Objective().Value() if objective_terms else 0
        allocation = [{'id': emp_id, 'overtime_hours': var.solution_value()} for emp_id, var in x.items()]
        add_log(full_result_ref, 'overtime', f"[{run_id}] 解が見つかりました", {"objective": obj_val, "num_allocations": len(allocation)})
        return {'status': 'OK', 'objective': obj_val, 'allocation': allocation, 'run_id': run_id}
    else:
        status_map = { pywraplp.Solver.INFEASIBLE: 'INFEASIBLE', pywraplp.Solver.UNBOUNDED: 'UNBOUNDED', 
                       pywraplp.Solver.ABNORMAL: 'ABNORMAL', pywraplp.Solver.NOT_SOLVED: 'NOT_SOLVED',
                       pywraplp.Solver.MODEL_INVALID: 'MODEL_INVALID' }
        status_str = status_map.get(status, f'UNKNOWN_STATUS_{status}')
        msg = f'残業配分問題で解が見つかりませんでした (ステータス: {status_str})。'
        add_log(full_result_ref, 'errors', f"[{run_id}] {msg}", {"status_code": status, "status_text": status_str})
        return {'status': status_str, 'message': msg, 'run_id': run_id}

# ---------- HTTPトリガー関数 ----------
@functions_framework.http
def solve_shift_http(request):
    """
    HTTPリクエストに応じてシフトスケジューリングと残業配分を実行する関数。
    リクエストボディには combined_input_data.json と同様の構造のJSONを期待する。
    また、クエリパラメータで time_limit_sec を指定可能。
    """
    # リクエストごとに結果を初期化
    current_full_result = {
        'logs': {'schedule': [], 'overtime': [], 'errors': [], 'warnings': [], 'info': []},
        'schedule_result': None,
        'overtime_result': None,
        'applied_constraints_history': []
    }
    run_id_main = f"http_main_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S%f')}"
    add_log(current_full_result, 'info', f"[{run_id_main}] HTTPリクエスト受信", {"headers": dict(request.headers)})
    
    request_json = request.get_json(silent=True)
    # Content-Typeの確認
    if not request_json:
        msg = "リクエストボディが空か、JSON形式ではありません。"
        add_log(current_full_result, 'errors', f"[{run_id_main}] {msg}")
        # ensure_ascii=False をレスポンスヘッダと dumps の両方に適用
        return (json.dumps({"error": msg, "logs": current_full_result['logs']}, ensure_ascii=False), 
                400, {'Content-Type': 'application/json; charset=utf-8'})

    schedule_input = request_json.get("schedule_input")
    cleaning_tasks_input = request_json.get("cleaning_tasks_input")

    if not schedule_input or not cleaning_tasks_input:
        msg = "リクエストJSONに必要なキー 'schedule_input' または 'cleaning_tasks_input' がありません。"
        add_log(current_full_result, 'errors', f"[{run_id_main}] {msg}")
        return (json.dumps({"error": msg, "logs": current_full_result['logs']}, ensure_ascii=False), 
                400, {'Content-Type': 'application/json; charset=utf-8'})

    time_limit_schedule_sec = request.args.get('time_limit_sec', str(DEFAULT_TIME_LIMIT_SEC)) # strで取得
    try:
        time_limit_schedule_sec = int(time_limit_schedule_sec)
        if time_limit_schedule_sec <= 0: time_limit_schedule_sec = DEFAULT_TIME_LIMIT_SEC
    except ValueError:
        add_log(current_full_result, 'warnings', f"[{run_id_main}] time_limit_sec の値が無効です ({request.args.get('time_limit_sec')})。デフォルト値 {DEFAULT_TIME_LIMIT_SEC} を使用します。")
        time_limit_schedule_sec = DEFAULT_TIME_LIMIT_SEC
    add_log(current_full_result, 'info', f"[{run_id_main}] スケジュールソルバーの制限時間: {time_limit_schedule_sec}秒")


    if 'settings' in schedule_input and 'facilities' in schedule_input and 'employees' in schedule_input:
        print(f"--- [{run_id_main}] シフトスケジューリングを開始 ---", file=sys.stderr)
        current_full_result['schedule_result'] = solve_schedule(current_full_result, schedule_input, cleaning_tasks_input, time_limit_schedule_sec, 0, None)
        print(f"--- [{run_id_main}] シフトスケジューリングを終了 ---", file=sys.stderr)
    else:
        msg = 'スケジューリングに必要な基本データ（settings, facilities, employees）が不足しています。'
        add_log(current_full_result, 'errors', f"[{run_id_main}] {msg}")
        current_full_result['schedule_result'] = {'status': 'NO_DATA_ERROR', 'message': msg, 'run_id': run_id_main}

    if 'overtime_lp' in schedule_input:
        print(f"--- [{run_id_main}] 残業時間最適配分を開始 ---", file=sys.stderr)
        current_full_result['overtime_result'] = solve_overtime_lp(current_full_result, schedule_input.get('overtime_lp', {}))
        print(f"--- [{run_id_main}] 残業時間最適配分を終了 ---", file=sys.stderr)
    else:
        add_log(current_full_result, 'info', f"[{run_id_main}] 入力データに overtime_lp セクションが存在しないため、残業配分処理をスキップします。")
        current_full_result['overtime_result'] = {'status': 'NOT_REQUESTED', 'message': '残業データが入力ファイルにありませんでした。', 'run_id': run_id_main}

    add_log(current_full_result, 'info', f"[{run_id_main}] HTTPリクエスト処理終了")
    return (json.dumps(current_full_result, indent=2, ensure_ascii=False), 
            200, {'Content-Type': 'application/json; charset=utf-8'})

# コマンドライン実行用の main 関数 (ローカルテスト用)
def local_main():
    global _local_full_result_for_testing_only # ローカルテスト専用のグローバル変数を使用
    run_id_main = f"local_main_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # _local_full_result_for_testing_only の 'logs' と 'applied_constraints_history' を初期化
    _local_full_result_for_testing_only['logs'] = {
        'schedule': [], 'overtime': [], 'errors': [], 'warnings': [], 'info': []
    }
    _local_full_result_for_testing_only['applied_constraints_history'] = []

    # add_log は _local_full_result_for_testing_only['logs'] に記録する想定
    add_log(_local_full_result_for_testing_only, 'info', f"[{run_id_main}] ローカル実行開始", {"arguments": sys.argv})

    if len(sys.argv) < 2:
        msg = '使用方法: python solve_new.py <combined_input_data.json>'
        add_log(_local_full_result_for_testing_only, 'errors', f"[{run_id_main}] {msg}")
        print(msg, file=sys.stderr) # ★標準エラーに出力
        # print(json.dumps(_local_full_result_for_testing_only, indent=2, ensure_ascii=False)) # ★この行を削除またはコメントアウト
        sys.exit(1) # エラーメッセージ出力後、終了
    
    combined_input_filepath = sys.argv[1]

    try:
        with open(combined_input_filepath, 'r', encoding='utf-8') as f: combined_input_data = json.load(f)
        add_log(_local_full_result_for_testing_only, 'info', f"[{run_id_main}] 結合入力ファイル '{combined_input_filepath}' の読み込み成功")
    except FileNotFoundError:
        error_msg = f"結合入力ファイル '{combined_input_filepath}' が見つかりません。"
        add_log(_local_full_result_for_testing_only, 'errors', f"[{run_id_main}] {error_msg}")
        print(error_msg, file=sys.stderr) # ★標準エラー
        # print(json.dumps(_local_full_result_for_testing_only, indent=2, ensure_ascii=False)); # ★削除
        sys.exit(1)
    except json.JSONDecodeError as e:
        error_msg = f"結合入力ファイル '{combined_input_filepath}' のJSON形式エラー: {e}"
        add_log(_local_full_result_for_testing_only, 'errors', f"[{run_id_main}] {error_msg}")
        print(error_msg, file=sys.stderr) # ★標準エラー
        # print(json.dumps(_local_full_result_for_testing_only, indent=2, ensure_ascii=False)); # ★削除
        sys.exit(1)

    schedule_input = combined_input_data.get("schedule_input")
    cleaning_tasks_input = combined_input_data.get("cleaning_tasks_input")

    if not schedule_input or not cleaning_tasks_input:
        msg = "結合入力JSONに必要なキー 'schedule_input' または 'cleaning_tasks_input' がありません。"
        add_log(_local_full_result_for_testing_only, 'errors', f"[{run_id_main}] {msg}")
        print(msg, file=sys.stderr) # ★標準エラー
        # print(json.dumps(_local_full_result_for_testing_only, indent=2, ensure_ascii=False)); # ★削除
        sys.exit(1)

    time_limit_schedule_sec = schedule_input.get("settings", {}).get("time_limit_sec", DEFAULT_TIME_LIMIT_SEC)
    add_log(_local_full_result_for_testing_only, 'info', f"[{run_id_main}] スケジュールソルバーの制限時間(ローカル): {time_limit_schedule_sec}秒")

    # 以下の print 文は既に file=sys.stderr になっているので問題なし
    if 'settings' in schedule_input and 'facilities' in schedule_input and 'employees' in schedule_input:
        print(f"--- [{run_id_main}] シフトスケジューリングを開始 ---", file=sys.stderr)
        _local_full_result_for_testing_only['schedule_result'] = solve_schedule(_local_full_result_for_testing_only, schedule_input, cleaning_tasks_input, time_limit_schedule_sec, 0, None)
        print(f"--- [{run_id_main}] シフトスケジューリングを終了 ---", file=sys.stderr)
    else:
        msg = 'スケジューリングに必要な基本データ（settings, facilities, employees）が不足しています。'
        add_log(_local_full_result_for_testing_only, 'errors', f"[{run_id_main}] {msg}")
        _local_full_result_for_testing_only['schedule_result'] = {'status': 'NO_DATA_ERROR', 'message': msg, 'run_id': run_id_main}

    if 'overtime_lp' in schedule_input:
        print(f"--- [{run_id_main}] 残業時間最適配分を開始 ---", file=sys.stderr)
        _local_full_result_for_testing_only['overtime_result'] = solve_overtime_lp(_local_full_result_for_testing_only, schedule_input.get('overtime_lp', {}))
        print(f"--- [{run_id_main}] 残業時間最適配分を終了 ---", file=sys.stderr)
    else:
        add_log(_local_full_result_for_testing_only, 'info', f"[{run_id_main}] 入力データに overtime_lp セクションが存在しないため、残業配分処理をスキップします。")
        _local_full_result_for_testing_only['overtime_result'] = {'status': 'NOT_REQUESTED', 'message': '残業データが入力ファイルにありませんでした。', 'run_id': run_id_main}

    add_log(_local_full_result_for_testing_only, 'info', f"[{run_id_main}] ローカル実行終了")
    
    # ★ 最終的なJSON結果をファイルに直接UTF-8で書き出す
    output_json_filepath = "solution.json" # 出力ファイル名を定義
    try:
        with open(output_json_filepath, 'w', encoding='utf-8') as f:
            json.dump(_local_full_result_for_testing_only, f, indent=2, ensure_ascii=False)
        print(f"結果を '{output_json_filepath}' に保存しました。", file=sys.stderr) # 標準エラーに進捗表示
    except IOError as e:
        print(f"エラー: 結果ファイル '{output_json_filepath}' の書き込みに失敗: {e}", file=sys.stderr)
        # エラーが発生した場合でも、標準出力には何も出さない

if __name__ == '__main__':
    local_main()
