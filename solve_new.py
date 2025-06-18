#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高度な従業員シフトスケジューリングおよび残業時間最適化ソルバー

local_main 実行方法:
    python solve_new.py generated_combined_input_data.json > solution.json
    ターミナルに直接表示（標準エラー出力なので）。もしファイルに保存したい場合は、
    python solve_new.py generated_combined_input_data.json > solution.json 2> run_debug.log

"""
import json, sys, math, datetime, os
import functions_framework # Cloud Run/Functions 用
from ortools.sat.python import cp_model
from ortools.linear_solver import pywraplp
from google.cloud import storage

# --- グローバル定数 ---
HOURS_IN_DAY = 24
MAX_RETRY_ATTEMPTS = 3 # ソフト制約緩和の最大試行回数
PENALTY_REDUCTION_FACTOR = 0.2 # ペナルティを緩和する際の係数
DEFAULT_TIME_LIMIT_SEC = 3600 # Cloud Run 用のデフォルト実行時間制限
GCS_BUCKET_NAME = "shift-optimization-result-storage"  # ★ あなたのGCSバケット名に置き換えてください
GCS_OBJECT_PREFIX = "result-folder/"   # ★ GCS内の保存先プレフィックス (例: "solver_results/")

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
# def _create_highs_solver(model_name="model"):
#     try:
#         return pywraplp.Solver.CreateSolver("HIGHS", model_name)
#     except TypeError:
#         s = pywraplp.Solver.CreateSolver("HIGHS")
#         s.SetSolverSpecificParametersAsString(f"ModelName={model_name}")
#         return s

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
    availability_matrix = {} # (emp_idx, day_idx, hour_idx) -> True
    night_shift_details_map = {}

    for emp_idx, emp in enumerate(employees_data):
        for avail_slot in emp.get('availability', []):
            try:
                day_of_week_spec = avail_slot['day_of_week']
                start_hour_int = parse_time_to_int(full_result_ref, avail_slot['start_time'])
                end_hour_int = parse_time_to_int(full_result_ref, avail_slot['end_time'])
                is_night_shift = avail_slot.get('is_night_shift', False)

                for day_idx_in_planning in range(num_total_days): # 計画期間内のすべての日をチェック
                    current_date = planning_start_date_obj + datetime.timedelta(days=day_idx_in_planning)
                    current_day_of_week_str = days_of_week_order[current_date.weekday()]

                    if current_day_of_week_str == day_of_week_spec: # スロットが定義された曜日と一致
                        # この day_idx_in_planning がスロットの開始日
                        if is_night_shift and end_hour_int < start_hour_int: # 日付またぎ夜勤
                            # 当日分
                            for h_today in range(start_hour_int, 24):
                                if 0 <= h_today < HOURS_IN_DAY:
                                    availability_matrix[(emp_idx, day_idx_in_planning, h_today)] = True
                            # 翌日分 (計画期間内であれば)
                            if day_idx_in_planning + 1 < num_total_days:
                                next_day_idx_in_planning = day_idx_in_planning + 1
                                for h_next_day in range(0, end_hour_int):
                                    if 0 <= h_next_day < HOURS_IN_DAY:
                                        availability_matrix[(emp_idx, next_day_idx_in_planning, h_next_day)] = True
                                # 夜勤詳細を記録 (開始日基準)
                                night_shift_details_map[(emp_idx, day_idx_in_planning)] = {
                                    "start_hour_on_start_day": start_hour_int,
                                    "end_hour_on_next_day": end_hour_int, # 翌日の終了時刻 (0-23)
                                    "is_night_shift": True
                                }
                        else: # 通常の日中シフトまたは日付をまたがない夜勤 (例: 22:00-24:00)
                            for hour_idx in range(start_hour_int, end_hour_int):
                                if 0 <= hour_idx < HOURS_IN_DAY:
                                    availability_matrix[(emp_idx, day_idx_in_planning, hour_idx)] = True
                            if is_night_shift: # 日付はまたがないが夜勤フラグがついている場合
                                night_shift_details_map[(emp_idx, day_idx_in_planning)] = {
                                    "start_hour_on_start_day": start_hour_int,
                                    "end_hour_on_start_day": end_hour_int,
                                    "is_night_shift": True
                                }

            except KeyError as e: add_log(full_result_ref, 'warnings', f"従業員 {emp.get('id', 'N/A')} の勤務可能時間データにキーエラー: {e}", {"employee_id": emp.get('id')})
            except ValueError as e: add_log(full_result_ref, 'warnings', f"従業員 {emp.get('id', 'N/A')} の時間関連データエラー: {e}", {"employee_id": emp.get('id')})
    
    # availability_matrix と night_shift_details_map を返す (あるいはタプルで)
    return availability_matrix, night_shift_details_map


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

def get_effective_penalty(base_penalty_config, global_multiplier, facility_override_value=None, facility_override_multiplier=None):
    base_val = base_penalty_config # settingsから取得した基本ペナルティ
    
    # 施設固有の直接指定値があればそれを優先
    if facility_override_value is not None:
        # print(f"Debug: Facility override value used: {facility_override_value}")
        return facility_override_value * global_multiplier # グローバルな緩和乗数は常に適用
    
    # 施設固有の乗数があればそれを適用
    if facility_override_multiplier is not None:
        # print(f"Debug: Facility override multiplier used: {facility_override_multiplier}")
        return base_val * facility_override_multiplier * global_multiplier
        
    # 施設固有の設定がなければグローバル設定のみ
    # print(f"Debug: Global penalty used: {base_val * global_multiplier}")
    return base_val * global_multiplier


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

    base_score_ph = settings.get("base_score_per_hour", 1) # 1時間あたりの基本スコア
    night_multi = settings.get("night_hour_multiplier", 1.0) # 夜勤時間のスコア倍率
    weekend_multi = settings.get("weekend_day_multiplier", 1.0) # 週末勤務のスコア倍率

    # --- データ構造の前処理 ---    

    # 施設と従業員のインデックスとIDマッピングを作成
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

    # availability の各スロットにユニークなインデックスを付ける
    all_availability_slots = []
    for emp_idx, emp in enumerate(employees_data):
        for slot_local_idx, avail_slot in enumerate(emp.get('availability', [])):
            avail_slot['employee_idx'] = emp_idx
            avail_slot['original_slot_idx'] = slot_local_idx
            avail_slot['global_slot_idx'] = len(all_availability_slots)
            all_availability_slots.append(avail_slot)

    # 難易度パラメータ取得とスコアマップ作成
    night_hours = set()
    # settings から NIGHT_HOURS_RANGE_FOR_DIFFICULTY を取得
    night_start_difficulty, night_end_difficulty = settings.get("NIGHT_HOURS_RANGE_FOR_DIFFICULTY", (22,5)) 
    if night_start_difficulty < night_end_difficulty:
        night_hours.update(range(night_start_difficulty, night_end_difficulty))
    else:
        night_hours.update(range(night_start_difficulty, 24))
        night_hours.update(range(0, night_end_difficulty))

    # 各シフト (f,d,h) の難易度スコアを事前に計算
    difficulty_score_map = {}
    for f_idx in F_indices: # 現状、施設による難易度変動は入れていないが拡張可能
        for d_idx in D_indices:
            current_date_obj = planning_start_date_obj + datetime.timedelta(days=d_idx)
            day_of_week_val = current_date_obj.weekday() # 月曜=0, 土曜=5, 日曜=6
            
            is_weekend = (day_of_week_val == 5 or day_of_week_val == 6)

            for h_idx in H_indices:
                score = float(base_score_ph) # floatで計算開始
                if h_idx in night_hours:
                    score *= night_multi
                if is_weekend:
                    score *= weekend_multi
                difficulty_score_map[(f_idx, d_idx, h_idx)] = score # floatで保持
    
    emp_avail_matrix, night_shift_details_map = get_employee_availability_matrix(full_result_ref, employees_data, num_total_days, days_of_week_order, planning_start_date_obj) # ★変更
    add_log(full_result_ref, 'info', f"[{run_id}] 従業員の勤務可能時間マトリックス作成完了")

    emp_preferred_facilities_idx_sets = [
        set(facility_id_to_idx[fid] for fid in emp.get('preferred_facilities', []) if fid in facility_id_to_idx)
        for emp in employees_data
    ]

    # --- モデルと変数定義 ---

    model = cp_model.CpModel()
    add_log(full_result_ref, 'schedule', f"[{run_id}] CP-SATモデルオブジェクト作成完了")

    # --- 決定変数 (疎な生成) ---
    # x[f, w, d, h]: 従業員wが施設fに日dの時間hに勤務するか
    # 勤務可能なスロットに対してのみ変数を生成する
    x = {} 
    for w_idx in W_indices:
        preferred_facilities_for_w = emp_preferred_facilities_idx_sets[w_idx]
        target_facilities = F_indices if not preferred_facilities_for_w else preferred_facilities_for_w
        for d_idx in D_indices:
            for h_idx in H_indices:
                if emp_avail_matrix.get((w_idx, d_idx, h_idx), False):
                    for f_idx in target_facilities:
                        x[(f_idx, w_idx, d_idx, h_idx)] = model.NewBoolVar(f'x_{f_idx}_{w_idx}_{d_idx}_{h_idx}')
    add_log(full_result_ref, 'schedule', f"[{run_id}] 決定変数 (x) の疎な生成完了", {"num_x_vars": len(x)})

    # 新しい決定変数 y[slot_idx, f] の生成
    y = {} 
    for slot in all_availability_slots:
        w_idx = slot['employee_idx']; slot_idx = slot['global_slot_idx']
        preferred_facilities_for_w = emp_preferred_facilities_idx_sets[w_idx]
        target_facilities = F_indices if not preferred_facilities_for_w else preferred_facilities_for_w
        for f_idx in target_facilities:
            y[(slot_idx, f_idx)] = model.NewBoolVar(f'y_slot{slot_idx}_fac{f_idx}')
    add_log(full_result_ref, 'schedule', f"[{run_id}] 決定変数 (y) の生成完了", {"num_y_vars": len(y)})

    # --- 補助変数 ---
    # works_on_day は従業員と日ごと
    works_on_day = { (w,d): model.NewBoolVar(f'works_w{w}_d{d}') for w in W_indices for d in D_indices }
    add_log(full_result_ref, 'schedule', f"[{run_id}] 補助変数 (works_on_day) 作成完了", {"num_works_on_day_vars": len(works_on_day)})

    # --- 制約設定の記録用 ---
    current_constraints_settings = {
        "run_id": run_id,
        "retry_attempt": retry_attempt,
        "hard_constraints": [
            "employee_availability_and_preferred_facility",
            "employee_one_facility_at_a_time",
            "works_on_day_definition",
            "overnight_shift_continuity", # 夜勤連続性
            "max_weekly_hours_40",        # 週40時間
            "min_rest_interval_8h",       # 勤務間インターバル
            "no_facility_change_within_day" # 同日施設変更禁止(近似)
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
                "multiplier": penalty_multipliers.get("staff_shortage", 1.0),
                "apply_difficulty_score_to_shortage": True
            },
            "difficulty_fairness": {
                "base_penalty": settings.get('fairness_penalty_weight_difficulty', 1000),
                "multiplier": penalty_multipliers.get("difficulty_fairness", 1.0)
            }
        }
    }

    if 'applied_constraints_history' not in full_result_ref: 
        full_result_ref['applied_constraints_history'] = [] # HTTP関数の場合、最初に初期化
    full_result_ref['applied_constraints_history'].append(current_constraints_settings)


    # --- ハード制約 ---

    add_log(full_result_ref, 'schedule', f"[{run_id}] ハード制約の追加開始")

    # 〇 従業員の勤務可能時間と希望施設
    # この部分は、変数生成ロジックに吸収されたため、明示的な制約は不要
    # for f_idx in F_indices:
    #     for w_idx in W_indices:
    #         if emp_preferred_facilities_idx_sets[w_idx] and f_idx not in emp_preferred_facilities_idx_sets[w_idx]:
    #              for d_idx in D_indices:
    #                 for h_idx in H_indices: model.Add(x[f_idx, w_idx, d_idx, h_idx] == 0)
    #                 # continue # この continue は不要。内側のループで処理が終わる。
    #         for d_idx in D_indices:
    #             for h_idx in H_indices:
    #                 if not emp_avail_matrix.get((w_idx, d_idx, h_idx), False):
    #                     model.Add(x[f_idx, w_idx, d_idx, h_idx] == 0)
    
    # 〇 従業員は同時に1つの施設でのみ勤務可能
    # この制約は、上記の連携制約によって自動的に満たされる。なぜなら、
    # 1. ある時間(d,h)にアサインされうるy変数は最大1つ (連携制約3のロジック)
    # 2. y変数は1つの施設にしか紐付かない
    # よって、ある時間(d,h)に従業員がアサインされる施設は最大1つになる。
    # 以前の x変数ベースの `sum(...) <= 1` は不要になる。
    # for w_idx in W_indices:
    #     for d_idx in D_indices:
    #         for h_idx in H_indices:
    #             # この従業員がこの日時に勤務可能な施設 (変数が存在する施設) のみを合計
    #             possible_shifts_at_this_time = [
    #                 x.get((f, w_idx, d_idx, h_idx)) 
    #                 for f in F_indices 
    #                 if x.get((f, w_idx, d_idx, h_idx)) is not None
    #             ]
    #             if possible_shifts_at_this_time:
    #                 model.Add(sum(possible_shifts_at_this_time) <= 1)

    # ★ 1. 「1リクエスト(スロット):1施設」制約 (y変数の制約)
    # 各 availability スロットは、最大で1つの施設にのみ割り当てられる
    add_log(full_result_ref, 'schedule', f"[{run_id}] ハード制約: 1リクエスト:1施設 追加")
    for slot in all_availability_slots:
        slot_idx = slot['global_slot_idx']
        assign_vars_for_slot = [v for k, v in y.items() if k[0] == slot_idx]
        if assign_vars_for_slot:
            model.Add(sum(assign_vars_for_slot) <= 1)

    # ★ 2. y変数とx変数の連携制約 (重要)
    # x[f,w,d,h] = 1 <=> (それをカバーするy[slot,f]のどれかが1)
    add_log(full_result_ref, 'schedule', f"[{run_id}] ハード制約: y変数とx変数の連携 追加")
    for (f_idx, w_idx, d_idx, h_idx), x_var in x.items():
        # このx_varに対応する(勤務可能である)y変数をすべて見つける
        possible_y_vars = []
        for slot in all_availability_slots:
            if slot['employee_idx'] == w_idx:
                # このスロットが(d_idx, h_idx)をカバーするかチェック
                covers_this_hour = False
                slot_date = planning_start_date_obj + datetime.timedelta(days=d_idx)
                if days_of_week_order[slot_date.weekday()] == slot['day_of_week']:
                    start_h = parse_time_to_int(full_result_ref, slot['start_time'])
                    end_h = parse_time_to_int(full_result_ref, slot['end_time'])
                    if slot.get('is_night_shift', False) and end_h < start_h: # 日またぎ
                        if start_h <= h_idx < 24: covers_this_hour = True
                    else:
                        if start_h <= h_idx < end_h: covers_this_hour = True
                elif slot.get('is_night_shift', False): # 翌日のチェック
                    prev_slot_date = slot_date - datetime.timedelta(days=1)
                    if days_of_week_order[prev_slot_date.weekday()] == slot['day_of_week']:
                        start_h = parse_time_to_int(full_result_ref, slot['start_time'])
                        end_h = parse_time_to_int(full_result_ref, slot['end_time'])
                        if end_h < start_h and 0 <= h_idx < end_h: covers_this_hour = True
                
                if covers_this_hour:
                    y_var = y.get((slot['global_slot_idx'], f_idx))
                    if y_var is not None:
                        possible_y_vars.append(y_var)
        
        # x_var <=> OR(possible_y_vars) の関係を定義
        if possible_y_vars:
            # x_varが1なら、yのどれかが1
            model.Add(sum(possible_y_vars) >= 1).OnlyEnforceIf(x_var)
            # yのどれかが1なら、x_varは1
            # (これは、yが1ならxが1という制約を各yについて課すことで実現できる)
            # このままだと y->x の片方向。双方向にするには以下が必要。
            # model.Add(sum(possible_y_vars) > 0).OnlyEnforceIf(x_var) と
            # model.Add(sum(possible_y_vars) == 0).OnlyEnforceIf(x_var.Not())
            # より直接的なのは AddBoolOr
            model.Add(x_var == model.NewBoolVar(f'or_y_for_x_{f_idx}_{w_idx}_{d_idx}_{h_idx}'))
            model.AddBoolOr(possible_y_vars).OnlyEnforceIf(x_var)
            model.AddImplication(x_var, model.NewBoolVar(f'placeholder_for_or_y_for_x_{f_idx}_{w_idx}_{d_idx}_{h_idx}').Not()) # この方法は複雑

            # ★★★ 最もシンプルで正しい実装 ★★★
            # x[f,w,d,h] = 1 であることと、それをカバーするy[slot, f]のいずれかが1であることが同値
            # x[f,w,d,h] <=> OR(y_1, y_2, ...)
            or_of_y_vars = model.NewBoolVar(f'or_y_{f_idx}_{w_idx}_{d_idx}_{h_idx}')
            model.AddBoolOr(possible_y_vars).OnlyEnforceIf(or_of_y_vars)
            model.Add(sum(possible_y_vars) == 0).OnlyEnforceIf(or_of_y_vars.Not())
            model.Add(x_var == or_of_y_vars)
        else:
            # このxをカバーするyが存在しない (通常は発生しないはず)
            model.Add(x_var == 0)

    # 〇 従業員がその日に1時間でも働いているか確認
    # 連続勤務日数と週あたり勤務日数の計算
    for w_idx in W_indices:
        for d_idx in D_indices:
            hours_worked_this_day = sum(x.get((f, w_idx, d_idx, h), 0) for f in F_indices for h in H_indices)
            model.Add(hours_worked_this_day > 0).OnlyEnforceIf(works_on_day[w_idx, d_idx])
            model.Add(hours_worked_this_day == 0).OnlyEnforceIf(works_on_day[w_idx, d_idx].Not())

    # 〇 週最大40時間
    MAX_WEEKLY_HOURS = 40
    for w_idx in W_indices:
        # 計画期間全体でチェック（7日を超える場合は、各7日間ブロックでチェック）
        for week_start_day_idx in range(0, num_total_days, 7):
            hours_in_week_segment = sum(x.get((f, w_idx, d, h), 0)
                                        for f in F_indices
                                        for d in range(week_start_day_idx, min(week_start_day_idx + 7, num_total_days))
                                        for h in H_indices)
            model.Add(hours_in_week_segment <= MAX_WEEKLY_HOURS)

    # 〇 勤務間インターバル8時間
    MIN_REST_HOURS = 8
    # 全時間スロットを1次元で扱う
    # ロジックを1次元のグローバル時間インデックス (global_h_idx) を使うように整理し、可読性を少し改善
    total_hours_in_period = num_total_days * HOURS_IN_DAY
    for w_idx in W_indices:
        for global_h_idx in range(total_hours_in_period):
            d_idx = global_h_idx // HOURS_IN_DAY
            h_idx = global_h_idx % HOURS_IN_DAY

            # この時間(global_h_idx)に勤務しているか
            works_at_h = model.NewBoolVar(f'w_{w_idx}_g{global_h_idx}')
            possible_shifts = [x.get((f, w_idx, d_idx, h_idx)) for f in F_indices if x.get((f, w_idx, d_idx, h_idx)) is not None]
            if possible_shifts:
                model.Add(sum(possible_shifts) == 1).OnlyEnforceIf(works_at_h)
                model.Add(sum(possible_shifts) == 0).OnlyEnforceIf(works_at_h.Not())
            else: # 勤務可能なシフトがなければ常に0
                model.Add(works_at_h == 0)

            # この時間(global_h_idx)に勤務を終了するかどうか (hに勤務、かつh+1に非勤務)
            is_end_of_shift_at_h = model.NewBoolVar(f'end_{w_idx}_g{global_h_idx}')
            if global_h_idx + 1 < total_hours_in_period:
                next_d_idx = (global_h_idx + 1) // HOURS_IN_DAY
                next_h_idx = (global_h_idx + 1) % HOURS_IN_DAY
                works_at_h_plus_1 = model.NewBoolVar(f'w_{w_idx}_g{global_h_idx+1}')
                possible_shifts_next = [x.get((f, w_idx, next_d_idx, next_h_idx)) for f in F_indices if x.get((f, w_idx, next_d_idx, next_h_idx)) is not None]
                if possible_shifts_next:
                    model.Add(sum(possible_shifts_next) == 1).OnlyEnforceIf(works_at_h_plus_1)
                    model.Add(sum(possible_shifts_next) == 0).OnlyEnforceIf(works_at_h_plus_1.Not())
                else:
                    model.Add(works_at_h_plus_1 == 0)
                
                model.AddBoolAnd([works_at_h, works_at_h_plus_1.Not()]).OnlyEnforceIf(is_end_of_shift_at_h)
                model.AddBoolOr([works_at_h.Not(), works_at_h_plus_1]).OnlyEnforceIf(is_end_of_shift_at_h.Not())
            else: # 計画期間の最後の時間スロット
                model.Add(is_end_of_shift_at_h == works_at_h)

            # 勤務終了後のインターバルを確保
            for rest_offset in range(1, MIN_REST_HOURS):
                rest_global_idx = global_h_idx + rest_offset
                if rest_global_idx < total_hours_in_period:
                    rest_d_idx = rest_global_idx // HOURS_IN_DAY
                    rest_h_idx = rest_global_idx % HOURS_IN_DAY
                    # この時間帯は勤務不可 (works_at_h の定義から、どの施設でも働けないことになる)
                    rest_works_var = model.NewBoolVar(f'w_{w_idx}_g{rest_global_idx}')
                    rest_possible_shifts = [x.get((f, w_idx, rest_d_idx, rest_h_idx)) for f in F_indices if x.get((f, w_idx, rest_d_idx, rest_h_idx)) is not None]
                    if rest_possible_shifts:
                        model.Add(sum(rest_possible_shifts) == 1).OnlyEnforceIf(rest_works_var)
                        model.Add(sum(rest_possible_shifts) == 0).OnlyEnforceIf(rest_works_var.Not())
                    else:
                        model.Add(rest_works_var == 0)

                    model.Add(rest_works_var == 0).OnlyEnforceIf(is_end_of_shift_at_h)

    # 〇 夜勤シフトの連続性保証 (日付またぎ)
    # 例えば、22時または23時に勤務開始し、それが夜勤とみなされるパターンを定義
    # 翌朝まで続いている場合に連続勤務を強制する
    # for w_idx in W_indices:
    #     for d_idx in D_indices:
    #         night_shift_info = night_shift_details_map.get((w_idx, d_idx))
    #         if night_shift_info and night_shift_info.get("is_night_shift") is True and "end_hour_on_next_day" in night_shift_info:
    #             start_h_today = night_shift_info["start_hour_on_start_day"]
    #             end_h_next_day = night_shift_info["end_hour_on_next_day"]
    #             if d_idx + 1 < num_total_days:
    #                 next_d_idx = d_idx + 1
    #                 for f_idx in F_indices:
    #                     first_hour_of_night_shift = x.get((f_idx, w_idx, d_idx, start_h_today))

    #                     # is not None を使って変数の存在をチェックするように修正 
    #                     if first_hour_of_night_shift is None: 
    #                         continue # この施設で夜勤開始の可能性がなければ(変数がなければ)スキップ

    #                     # 当日の残り時間と翌日の継続時間を強制
    #                     for h_today in range(start_h_today + 1, 24):
    #                         var = x.get((f_idx, w_idx, d_idx, h_today))
    #                         if var is not None:
    #                             model.Add(var == 1).OnlyEnforceIf(first_hour_of_night_shift)
    #                     for h_next_day in range(0, end_h_next_day):
    #                         var = x.get((f_idx, w_idx, next_d_idx, h_next_day))
    #                         if var is not None:
    #                             model.Add(var == 1).OnlyEnforceIf(first_hour_of_night_shift)

    #                     # 他の施設では働けない
    #                     for other_f_idx in F_indices:
    #                         if other_f_idx != f_idx:
    #                             for h_today in range(start_h_today, 24): # start_h_todayも含む
    #                                 var = x.get((other_f_idx, w_idx, d_idx, h_today))
    #                                 if var is not None:
    #                                     model.Add(var == 0).OnlyEnforceIf(first_hour_of_night_shift)
    #                             for h_next_day in range(0, end_h_next_day):
    #                                 var = x.get((other_f_idx, w_idx, next_d_idx, h_next_day))
    #                                 if var is not None:
    #                                     model.Add(var == 0).OnlyEnforceIf(first_hour_of_night_shift)

    # 〇 深夜・早朝 (21-9時) の連続時間での施設移動禁止 (ハード制約)
    # for w_idx in W_indices:
    #     # 日付またぎも考慮して全時間スロットを1次元でチェック
    #     for global_h_idx in range(total_hours_in_period - 1):
    #         next_global_h_idx = global_h_idx + 1
            
    #         d_idx1 = global_h_idx // HOURS_IN_DAY; h_idx1 = global_h_idx % HOURS_IN_DAY
    #         d_idx2 = next_global_h_idx // HOURS_IN_DAY; h_idx2 = next_global_h_idx % HOURS_IN_DAY
            
    #         # h_idx1 が 22-翌8時 の範囲に含まれるか
    #         is_in_no_move_zone = (h_idx1 >= 21 or h_idx1 < 9)
            
    #         if is_in_no_move_zone:
    #             for f1_idx in F_indices:
    #                 for f2_idx in F_indices:
    #                     if f1_idx == f2_idx: continue

    #                     var1 = x.get((f1_idx, w_idx, d_idx1, h_idx1))
    #                     var2 = x.get((f2_idx, w_idx, d_idx2, h_idx2))
                        
    #                     if var1 is not None and var2 is not None:
    #                         # 連続した時間での異施設勤務を禁止
    #                         model.AddBoolOr([var1.Not(), var2.Not()])

    # 〇 最低勤務時間制約 (10-15時以外は2時間以上)
    # MIN_WORK_HOURS = 2
    # SPECIAL_HOURS_FOR_1H_SHIFT = set(range(10, 15)) # 10時から14時台

    # for w_idx in W_indices:
    #     for d_idx in D_indices:
    #         for h_idx in range(MIN_WORK_HOURS):
    #             # この時間hが「1時間だけの勤務」になることを禁止する
                
    #             # h時に勤務しているか
    #             works_at_h = model.NewBoolVar(f'min_h_w{w_idx}_d{d_idx}_h{h_idx}')
    #             vars_h = [v for k,v in x.items() if k[1]==w_idx and k[2]==d_idx and k[3]==h_idx]
    #             if vars_h: model.Add(sum(vars_h) == 1).OnlyEnforceIf(works_at_h); model.Add(sum(vars_h) == 0).OnlyEnforceIf(works_at_h.Not())
    #             else: model.Add(works_at_h == 0)

    #             # h-1時に勤務しているか
    #             works_at_hm1 = model.NewBoolVar(f'min_hm1_w{w_idx}_d{d_idx}_h{h_idx}')
    #             if h_idx > 0:
    #                 vars_hm1 = [v for k,v in x.items() if k[1]==w_idx and k[2]==d_idx and k[3]==h_idx-1]
    #                 if vars_hm1: model.Add(sum(vars_hm1) == 1).OnlyEnforceIf(works_at_hm1); model.Add(sum(vars_hm1) == 0).OnlyEnforceIf(works_at_hm1.Not())
    #                 else: model.Add(works_at_hm1 == 0)
    #             else: # 0時の前は勤務していない
    #                 model.Add(works_at_hm1 == 0)

    #             # h+1時に勤務しているか
    #             works_at_hp1 = model.NewBoolVar(f'min_hp1_w{w_idx}_d{d_idx}_h{h_idx}')
    #             if h_idx < MIN_WORK_HOURS - 1:
    #                 vars_hp1 = [v for k,v in x.items() if k[1]==w_idx and k[2]==d_idx and k[3]==h_idx+1]
    #                 if vars_hp1: model.Add(sum(vars_hp1) == 1).OnlyEnforceIf(works_at_hp1); model.Add(sum(vars_hp1) == 0).OnlyEnforceIf(works_at_hp1.Not())
    #                 else: model.Add(works_at_hp1 == 0)
    #             else: # 最終時間の次は勤務していない
    #                 model.Add(works_at_hp1 == 0)
                
    #             # 「1時間だけの勤務」= (h-1に非勤務) AND (hに勤務) AND (h+1に非勤務)
    #             is_one_hour_isolated_shift = model.NewBoolVar(f'iso_1h_w{w_idx}_d{d_idx}_h{h_idx}')
    #             model.AddBoolAnd([works_at_hm1.Not(), works_at_h, works_at_hp1.Not()]).OnlyEnforceIf(is_one_hour_isolated_shift)

    #             # この1時間勤務が特別時間帯でなければ禁止
    #             # コメントアウト
    #             # is_in_special_hours = h_idx in SPECIAL_HOURS_FOR_1H_SHIFT
    #             # if not is_in_special_hours:
    #             model.Add(is_one_hour_isolated_shift == 0)
    
    # 〇 1日の最大勤務施設数制約 (最大2施設まで => 移動は最大1回。3回以上移動なら最低3施設必要)
    # 3回以上の移動(A->B->C->D)を禁止するには、勤務施設数を3以下に制限すればよい。
    # MAX_WORKED_FACILITIES_PER_DAY = 2

    # for w_idx in W_indices:
    #     for d_idx in D_indices:
            
    #         # 各施設で、この日に勤務したかどうかを示すブール変数
    #         worked_at_facility = []
    #         for f_idx in F_indices:
    #             works_at_f_this_day = model.NewBoolVar(f'work_at_f{f_idx}_w{w_idx}_d{d_idx}')
                
    #             # この施設・この日の勤務変数リストを取得
    #             daily_facility_shifts = [v for (f,w,d,h),v in x.items() if w==w_idx and d==d_idx and f==f_idx]
                
    #             if daily_facility_shifts:
    #                 # 1時間でも勤務があれば True
    #                 model.Add(sum(daily_facility_shifts) >= 1).OnlyEnforceIf(works_at_f_this_day)
    #                 model.Add(sum(daily_facility_shifts) == 0).OnlyEnforceIf(works_at_f_this_day.Not())
    #             else: # 勤務可能なスロットがなければ常に False
    #                 model.Add(works_at_f_this_day == 0)
                
    #             worked_at_facility.append(works_at_f_this_day)
            
    #         # 勤務した施設の種類の合計が上限を超えないようにする
    #         if worked_at_facility:
    #             model.Add(sum(worked_at_facility) <= MAX_WORKED_FACILITIES_PER_DAY)

    # 〇 10-15時を除いて 同日内での施設変更禁止 (1リクエスト:1施設の近似)
    # SPECIAL_MOVE_START_HOUR = 10; SPECIAL_MOVE_END_HOUR = 15; MOVE_TIME_HOURS = 1
    # for w_idx in W_indices:
    #     for d_idx in D_indices:
    #         for h_idx in range(HOURS_IN_DAY):
    #             # この時間に勤務を終了するかどうかを判定
    #             works_at_h = model.NewBoolVar(f'is_work_w{w_idx}_d{d_idx}_h{h_idx}') # 変数名が重複しないように
    #             possible_shifts_h = [x.get((f,w_idx,d_idx,h_idx)) for f in F_indices if x.get((f,w_idx,d_idx,h_idx)) is not None]
    #             if possible_shifts_h: model.Add(sum(possible_shifts_h)==1).OnlyEnforceIf(works_at_h); model.Add(sum(possible_shifts_h)==0).OnlyEnforceIf(works_at_h.Not())
    #             else: model.Add(works_at_h == 0)

    #             is_end_of_shift_at_h = model.NewBoolVar(f'is_end_w{w_idx}_d{d_idx}_h{h_idx}')
    #             if h_idx + 1 < HOURS_IN_DAY:
    #                 works_at_h_plus_1 = model.NewBoolVar(f'is_work_w{w_idx}_d{d_idx}_h{h_idx+1}')
    #                 possible_shifts_h1 = [x.get((f,w_idx,d_idx,h_idx+1)) for f in F_indices if x.get((f,w_idx,d_idx,h_idx+1)) is not None]
    #                 if possible_shifts_h1: model.Add(sum(possible_shifts_h1)==1).OnlyEnforceIf(works_at_h_plus_1); model.Add(sum(possible_shifts_h1)==0).OnlyEnforceIf(works_at_h_plus_1.Not())
    #                 else: model.Add(works_at_h_plus_1 == 0)
    #                 model.AddBoolAnd([works_at_h, works_at_h_plus_1.Not()]).OnlyEnforceIf(is_end_of_shift_at_h)
    #                 model.AddBoolOr([works_at_h.Not(), works_at_h_plus_1]).OnlyEnforceIf(is_end_of_shift_at_h.Not())
    #             else: model.Add(is_end_of_shift_at_h == works_at_h)
                
    #             # h時に勤務を終了し、かつそれが特別移動時間帯内であれば、h+1は移動時間
    #             is_in_special_move_time = (SPECIAL_MOVE_START_HOUR <= h_idx < SPECIAL_MOVE_END_HOUR)
    #             if is_in_special_move_time:
    #                 next_h_idx = h_idx + MOVE_TIME_HOURS
    #                 if next_h_idx < HOURS_IN_DAY:
    #                     works_at_move_hour = model.NewBoolVar(f'is_work_w{w_idx}_d{d_idx}_h{next_h_idx}')
    #                     possible_shifts_move = [x.get((f,w_idx,d_idx,next_h_idx)) for f in F_indices if x.get((f,w_idx,d_idx,next_h_idx)) is not None]
    #                     if possible_shifts_move: model.Add(sum(possible_shifts_move)>=1).OnlyEnforceIf(works_at_move_hour); model.Add(sum(possible_shifts_move)==0).OnlyEnforceIf(works_at_move_hour.Not())
    #                     else: model.Add(works_at_move_hour == 0)
    #                     model.Add(works_at_move_hour == 0).OnlyEnforceIf(is_end_of_shift_at_h)
    
    add_log(full_result_ref, 'schedule', f"[{run_id}] 全てのハード制約の追加完了")
    add_model_stats_log(full_result_ref, model, 'schedule', f"[{run_id}] ハード制約追加後のモデル状態")

    # --- ソフト制約 ---

    # 緩和対象のペナルティを明確に区別
    soft_penalty_terms = []
    objective_terms = []

    # スケールファクタを定義
    # ここでは、浮動小数点数スコア（コスト）を1000倍して整数として扱う        
    SCALE_FACTOR = 1000 # 1000なら小数点数3位までのコスト精度を確保
    
    # 〇 最大連続勤務日数 (ソフト制約)
    max_consecutive_setting = settings.get('max_consecutive_work_days', 5)
    base_consecutive_penalty = current_constraints_settings["soft_constraints_settings"]["consecutive_days"]["base_penalty"]
    current_consecutive_multiplier = current_constraints_settings["soft_constraints_settings"]["consecutive_days"]["multiplier"]
    effective_consecutive_penalty = int(round(base_consecutive_penalty * current_consecutive_multiplier)) # 整数化

    if max_consecutive_setting > 0 and num_total_days > max_consecutive_setting:
        for w_idx in W_indices:
            for d_idx_start in range(num_total_days - max_consecutive_setting):
                consecutive_days_worked = sum(works_on_day[w_idx, d] for d in range(d_idx_start, d_idx_start + max_consecutive_setting + 1))
                excess_consecutive = model.NewIntVar(0, max_consecutive_setting + 2, f'ex_consec_w{w_idx}_d{d_idx_start}')
                
                is_exceeding = model.NewBoolVar(f'is_ex_consec_w{w_idx}_d{d_idx_start}')
                model.Add(consecutive_days_worked > max_consecutive_setting).OnlyEnforceIf(is_exceeding)
                model.Add(consecutive_days_worked <= max_consecutive_setting).OnlyEnforceIf(is_exceeding.Not())
                model.Add(excess_consecutive == consecutive_days_worked - max_consecutive_setting).OnlyEnforceIf(is_exceeding)
                model.Add(excess_consecutive == 0).OnlyEnforceIf(is_exceeding.Not())
                soft_penalty_terms.append(excess_consecutive * effective_consecutive_penalty)

    # 〇 週あたりの最大労働日数 (ソフト制約)
    base_weekly_days_penalty = current_constraints_settings["soft_constraints_settings"]["weekly_days"]["base_penalty"]
    current_weekly_days_multiplier = current_constraints_settings["soft_constraints_settings"]["weekly_days"]["multiplier"]
    effective_weekly_days_penalty = int(round(base_weekly_days_penalty * current_weekly_days_multiplier))

    for w_idx in W_indices:
        max_days_week = employees_data[w_idx].get('contract_max_days_per_week', 7)
        for week_start_day_idx in range(0, num_total_days, 7):
            days_in_week = sum(works_on_day[w_idx, d_idx] for d_idx in range(week_start_day_idx, min(week_start_day_idx + 7, num_total_days)))
            excess_weekly_days = model.NewIntVar(0, 8, f'ex_week_w{w_idx}_wk{week_start_day_idx}')
            
            is_exceeding = model.NewBoolVar(f'is_ex_week_w{w_idx}_wk{week_start_day_idx}')
            model.Add(days_in_week > max_days_week).OnlyEnforceIf(is_exceeding)
            model.Add(days_in_week <= max_days_week).OnlyEnforceIf(is_exceeding.Not())
            model.Add(excess_weekly_days == days_in_week - max_days_week).OnlyEnforceIf(is_exceeding)
            model.Add(excess_weekly_days == 0).OnlyEnforceIf(is_exceeding.Not())
            soft_penalty_terms.append(excess_weekly_days * effective_weekly_days_penalty)

    # 〇 1日あたりの最大労働時間 (ソフト制約)
    base_daily_hours_penalty = current_constraints_settings["soft_constraints_settings"]["daily_hours"]["base_penalty"]
    current_daily_hours_multiplier = current_constraints_settings["soft_constraints_settings"]["daily_hours"]["multiplier"]
    effective_daily_hours_penalty = int(round(base_daily_hours_penalty * current_daily_hours_multiplier))

    for w_idx in W_indices:
        max_hours_day = employees_data[w_idx].get('contract_max_hours_per_day', HOURS_IN_DAY)
        for d_idx in D_indices:

            hours_worked = sum(x.get((f_idx, w_idx, d_idx, h_idx), 0) for f_idx in F_indices for h_idx in H_indices)
            excess_daily_hours = model.NewIntVar(0, HOURS_IN_DAY + 1, f'ex_day_w{w_idx}_d{d_idx}')
            
            is_exceeding = model.NewBoolVar(f'is_ex_day_w{w_idx}_d{d_idx}')
            model.Add(hours_worked > max_hours_day).OnlyEnforceIf(is_exceeding)
            model.Add(hours_worked <= max_hours_day).OnlyEnforceIf(is_exceeding.Not())
            model.Add(excess_daily_hours == hours_worked - max_hours_day).OnlyEnforceIf(is_exceeding)
            model.Add(excess_daily_hours == 0).OnlyEnforceIf(is_exceeding.Not())
            soft_penalty_terms.append(excess_daily_hours * effective_daily_hours_penalty)

    # 〇 各日の必要人数の充足 (ソフト制約)
    base_staff_shortage_penalty_config = current_constraints_settings["soft_constraints_settings"]["staff_shortage"]["base_penalty"]
    current_staff_shortage_global_multiplier = current_constraints_settings["soft_constraints_settings"]["staff_shortage"]["multiplier"]
    apply_difficulty_to_shortage = current_constraints_settings["soft_constraints_settings"]["staff_shortage"]["apply_difficulty_score_to_shortage"]

    for f_idx in F_indices:

        facility_details = facilities_data[f_idx]
        facility_penalty_overrides = facility_details.get("penalty_overrides", {}) # ★施設固有設定を取得
        facility_shortage_override_multiplier = facility_penalty_overrides.get("staff_shortage_multiplier")        

        # スタッフ不足ペナルティの施設固有乗数を取得
        base_shortage_penalty_for_facility = base_staff_shortage_penalty_config
        if facility_shortage_override_multiplier is not None:
             base_shortage_penalty_for_facility *= facility_shortage_override_multiplier
        
        effective_base_penalty_for_facility = base_shortage_penalty_for_facility * current_staff_shortage_global_multiplier

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
                
                # 疎な変数生成に対応
                staff_count = sum(x.get((f_idx, w_idx, d_idx, h_idx), 0) for w_idx in W_indices)
                actual_shortage = model.NewIntVar(0, max(1, num_employees), f'sh_f{f_idx}_d{d_idx}_h{h_idx}')

                # 不足人数を計算 (>= 0)
                model.Add(actual_shortage >= required_staff_target - staff_count)

                penalty_value_for_this_slot = effective_base_penalty_for_facility

                # ★コンテキストによる難易度スコアの精緻化
                # 元々の時間帯・曜日の難易度スコアを取得
                base_shift_difficulty_score = difficulty_score_map.get((f_idx, d_idx, h_idx), base_score_ph)
                
                # コンテキストに応じた追加乗数
                context_multiplier = 1.0
                # 清掃シフト時間帯以外の不足はより重大と見なす（常駐義務違反）
                if cleaning_start_h >= h_idx > cleaning_end_h:
                    context_multiplier *= settings.get("cleaning_shift_shortage_multiplier", 1.5) # 例: 1.5倍のペナルティ
                # 他の重要なコンテキスト（例: イベント日など）もここに追加可能

                # 最終的な難易度スコアを計算
                final_shift_difficulty_score = base_shift_difficulty_score * context_multiplier
                
                if apply_difficulty_to_shortage:
                    penalty_value_for_this_slot *= final_shift_difficulty_score
                
                # スケーリングを適用して整数化
                final_penalty_per_short_person = int(round(penalty_value_for_this_slot * SCALE_FACTOR))
                soft_penalty_terms.append(actual_shortage * final_penalty_per_short_person)

    # 〇 施設移動に対するペナルティ (ソフト制約)
    # SPECIAL_MOVE_START_HOUR = 10
    # SPECIAL_MOVE_END_HOUR = 15 # 14時台まで
    # facility_move_base_penalty = settings.get("facility_move_penalty", 200000000) # 非常に高いペナルティコスト

    # for w_idx in W_indices:
    #     for d_idx in D_indices:
    #         for h_idx in range(HOURS_IN_DAY - 2): # 移動時間(1h)と次の勤務(1h)を考慮
                
    #             # この時間hが、移動が許可されている時間帯であるか
    #             is_in_special_move_time = (SPECIAL_MOVE_START_HOUR <= h_idx < SPECIAL_MOVE_END_HOUR)

    #             # h時に施設f1で勤務を終え、1時間移動し、h+2時に施設f2で勤務開始する移動を検出
    #             for f1_idx in F_indices:
    #                 var_at_h_f1 = x.get((f1_idx, w_idx, d_idx, h_idx))
    #                 if var_at_h_f1 is None: continue

    #                 # h+1 は移動時間なので非勤務である必要がある
    #                 works_at_h1 = model.NewBoolVar(f'w_{w_idx}_{d_idx}_{h_idx+1}_anyf')
    #                 possible_h1 = [v for k,v in x.items() if k[1]==w_idx and k[2]==d_idx and k[3]==h_idx+1]
    #                 if possible_h1: model.Add(sum(possible_h1)==0).OnlyEnforceIf(works_at_h1.Not()); model.Add(sum(possible_h1)>=1).OnlyEnforceIf(works_at_h1)
    #                 else: model.Add(works_at_h1==0)

    #                 # h時にf1勤務、h+1時に非勤務 (勤務終了)
    #                 end_at_h_f1 = model.NewBoolVar(f'end_{w_idx}_{d_idx}_{h_idx}_f{f1_idx}')
    #                 model.AddBoolAnd([var_at_h_f1, works_at_h1.Not()]).OnlyEnforceIf(end_at_h_f1)
                    
    #                 for f2_idx in F_indices:
    #                     if f1_idx == f2_idx: continue
                        
    #                     next_work_h = h_idx + 2
    #                     var_at_h2_f2 = x.get((f2_idx, w_idx, d_idx, next_work_h))
    #                     if var_at_h2_f2 is None: continue

    #                     # h時にf1で終了し、h+2時にf2で開始するイベント
    #                     move_event = model.NewBoolVar(f'move_{w_idx}_{d_idx}_{h_idx}_{f1_idx}to{f2_idx}')
    #                     model.AddBoolAnd([end_at_h_f1, var_at_h2_f2]).OnlyEnforceIf(move_event)
                        
    #                     if is_in_special_move_time:
    #                         # 特別時間帯の1hインターバル移動はペナルティなし
    #                         pass 
    #                     else:
    #                         # 通常時間帯(9時、15-21時)の1hインターバル移動にペナルティ
    #                         soft_penalty_terms.append(move_event * facility_move_base_penalty)


    # 〇 従業員間の総獲得難易度スコアの公平性 (ソフト制約)
    total_difficulty_per_employee_vars = []
    max_possible_difficulty_score = int(HOURS_IN_DAY * 7 * max(weekend_multi, night_multi, 1) * SCALE_FACTOR * 2) # 余裕を持った上限値
    
    for w_idx in W_indices:
        employee_total_difficulty_scaled = model.NewIntVar(0, max_possible_difficulty_score, f'total_diff_s_w{w_idx}')
        
        # ★ 疎な変数生成に対応
        terms_scaled = []
        for (f, w, d, h), var in x.items(): # 変数が存在する組み合わせのみループ
            if w == w_idx:
                scaled_score = int(round(difficulty_score_map.get((f, d, h), base_score_ph) * SCALE_FACTOR))
                terms_scaled.append(var * scaled_score)
        
        if terms_scaled:
            model.Add(employee_total_difficulty_scaled == sum(terms_scaled))
        else: # この従業員が働けるスロットが一つもない場合
            model.Add(employee_total_difficulty_scaled == 0)
            
        total_difficulty_per_employee_vars.append(employee_total_difficulty_scaled)
    
    if total_difficulty_per_employee_vars:
        max_total_difficulty_var_s = model.NewIntVar(0, max_possible_difficulty_score, 'max_total_diff_s')
        min_total_difficulty_var_s = model.NewIntVar(0, max_possible_difficulty_score, 'min_total_diff_s')
        model.AddMaxEquality(max_total_difficulty_var_s, total_difficulty_per_employee_vars)
        model.AddMinEquality(min_total_difficulty_var_s, total_difficulty_per_employee_vars)
        
        difficulty_spread_penalty_var_s = model.NewIntVar(0, max_possible_difficulty_score, 'diff_spread_pen_s')
        model.Add(difficulty_spread_penalty_var_s == max_total_difficulty_var_s - min_total_difficulty_var_s)
        
        base_fairness_penalty = current_constraints_settings["soft_constraints_settings"]["difficulty_fairness"]["base_penalty"]
        current_fairness_multiplier = current_constraints_settings["soft_constraints_settings"]["difficulty_fairness"]["multiplier"]
        
        # ★ 公平性ペナルティの重み自体はスケーリングしない。差分がスケーリングされているため。
        effective_fairness_penalty_weight = int(round(base_fairness_penalty * current_fairness_multiplier))
        soft_penalty_terms.append(difficulty_spread_penalty_var_s * effective_fairness_penalty_weight)

    # 〇 目的関数（シフトが実際に組まれた場合に直接的に発生するコストや評価）
    # objective_terms と soft_penalty_terms を分けておく方が、緩和対象のペナルティを明確に区別でき、シンプルロジックを維持できる
    global_diff_multiplier = settings.get("global_difficulty_cost_multiplier", 0.1)

    for (f, w, d, h), var in x.items():
        difficulty_cost_float = difficulty_score_map.get((f, d, h), base_score_ph)
        # スケーリングを適用
        additional_difficulty_cost_scaled = int(round(difficulty_cost_float * global_diff_multiplier * SCALE_FACTOR))
        objective_terms.append(var * additional_difficulty_cost_scaled)
    
    # 直接的なコストと、制約違反のペナルティの合計を最小化する
    model.Minimize(sum(objective_terms) + sum(soft_penalty_terms))

    add_log(full_result_ref, 'schedule', f"[{run_id}] 目的関数設定完了")
    add_model_stats_log(full_result_ref, model, 'schedule', f"[{run_id}] 目的関数設定後のモデル状態")
    
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = settings.get('time_limit_sec', 60)
    solver.parameters.log_search_progress = True
    # Cloud Run環境でのリソース制限を考慮
    MAX_WORKERS = min(8, os.cpu_count() or 1)  # より安全な実装例
    solver.parameters.num_search_workers = MAX_WORKERS

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
        
        # アサイン情報に難易度スコアも追加
        assignments_with_difficulty = [] 
        for w_idx in W_indices:
            emp_id = employee_idx_to_id[w_idx]
            for d_idx in D_indices:
                current_date_str = (planning_start_date_obj + datetime.timedelta(days=d_idx)).strftime("%Y-%m-%d")                
                for f_idx in F_indices:
                    facility_id = facility_idx_to_id[f_idx]
                    current_block_start_hour = -1
                    current_block_difficulty_scores = [] 

                    for h_idx in H_indices:
                        var = x.get((f_idx, w_idx, d_idx, h_idx))
                        if var is not None and solver.Value(var) == 1:
                            if current_block_start_hour == -1:
                                current_block_start_hour = h_idx
                            current_block_difficulty_scores.append(difficulty_score_map.get((f_idx, d_idx, h_idx), 0))
                        else:
                            if current_block_start_hour != -1:
                                # 平均スコアを計算
                                total_difficulty = sum(current_block_difficulty_scores)
                                avg_difficulty = total_difficulty / len(current_block_difficulty_scores) if current_block_difficulty_scores else 0
                                assignments_with_difficulty.append({
                                    "employee_id": emp_id,
                                    "facility_id": facility_id,
                                    "date": current_date_str,
                                    "start_hour": current_block_start_hour,
                                    "end_hour": h_idx,
                                    "difficulty_score_avg": round(avg_difficulty, 2),
                                })
                                current_block_start_hour = -1
                                current_block_difficulty_scores = []

                    if current_block_start_hour != -1:
                        total_difficulty = sum(current_block_difficulty_scores)
                        avg_difficulty = total_difficulty / len(current_block_difficulty_scores) if current_block_difficulty_scores else 0
                        assignments_with_difficulty.append({
                            "employee_id": emp_id,
                            "facility_id": facility_id,
                            "date": current_date_str,
                            "start_hour": current_block_start_hour,
                            "end_hour": HOURS_IN_DAY,
                            "difficulty_score_avg": round(avg_difficulty, 2),
                        })
                        
        result['assignments'] = assignments_with_difficulty

        # 不足シフトとその難易度スコアを記録
        shortage_shifts_with_difficulty = []
        for f_idx in F_indices:
            facility_id = facility_idx_to_id[f_idx]
            facility_details = facilities_data[f_idx] # staff_shortageペナルティ計算と同様のロジック
            facility_cleaning_capacity_per_hr = facility_details.get('cleaning_capacity_tasks_per_hour_per_employee', 1)
            if facility_cleaning_capacity_per_hr <= 0: facility_cleaning_capacity_per_hr = 1

            for d_idx in D_indices:
                current_date_obj = planning_start_date_obj + datetime.timedelta(days=d_idx)
                date_str = current_date_obj.strftime("%Y-%m-%d")
                daily_cleaning_tasks = get_cleaning_tasks_for_day_facility(full_result_ref, facility_id, current_date_obj, cleaning_tasks_data, days_of_week_order)
                
                for h_idx in H_indices:
                    required_staff_target = 1
                    if cleaning_start_h <= h_idx < cleaning_end_h:
                        if cleaning_hours_duration > 0 and daily_cleaning_tasks > 0:
                            required_staff_target = max(1, math.ceil(daily_cleaning_tasks / (facility_cleaning_capacity_per_hr * cleaning_hours_duration)))
                        else: required_staff_target = 1
                    
                    current_assigned_staff = 0
                    for w_idx_check in W_indices: # この時間、この施設にアサインされた人数を再計算
                        var_check = x.get((f_idx, w_idx_check, d_idx, h_idx))
                        if var_check is not None and solver.Value(var_check) == 1:
                            current_assigned_staff += 1
                    
                    actual_shortage_count = required_staff_target - current_assigned_staff
                    
                    if actual_shortage_count > 0:
                        shift_difficulty = difficulty_score_map.get((f_idx, d_idx, h_idx), 0)
                        shortage_shifts_with_difficulty.append({
                            "facility_id": facility_id,
                            "date": date_str,
                            "hour": h_idx,
                            "shortage_count": actual_shortage_count,
                            "required_staff": required_staff_target,
                            "assigned_staff": current_assigned_staff,
                            "difficulty_score_of_short_shift": round(shift_difficulty, 2)
                        })

        result['shortage_shifts_details'] = shortage_shifts_with_difficulty

        # 各従業員の情報を保持する辞書を事前に初期化
        hours_per_employee = {emp_id: 0 for emp_id in employee_idx_to_id.values()}
        difficulty_per_employee = {emp_id: 0 for emp_id in employee_idx_to_id.values()}

        # 存在する変数 (x.items()) を一度だけループする効率的な方法
        for (f, w, d, h), var in x.items():
            if solver.Value(var) == 1:
                emp_id = employee_idx_to_id[w]
                # 総労働時間を加算
                hours_per_employee[emp_id] += 1
                # 総獲得難易度スコアを加算
                difficulty_per_employee[emp_id] += difficulty_score_map.get((f, d, h), 0)

        # 総勤務日数の計算 (これは works_on_day を使うので変更なし)
        days_per_employee = {}
        for w_idx in W_indices:
            emp_id = employee_idx_to_id[w_idx]
            total_days = sum(solver.Value(works_on_day[w_idx, d_idx]) for d_idx in D_indices)
            days_per_employee[emp_id] = total_days

        result["diagnostics"] = {
            "hours_worked_per_employee": hours_per_employee,
            "days_worked_per_employee": days_per_employee,
            "total_difficulty_score_per_employee": {
                emp_id: round(score, 2) for emp_id, score in difficulty_per_employee.items()
            }
        }

        add_log(full_result_ref, 'schedule', f"[{run_id}] 結果の整形完了", {"num_assignments": len(assignments_with_difficulty)})
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

# ---------- HTTPトリガー関数 ----------
@functions_framework.http
def shift_optimazation(request):
    """
    cloud functions の HTTP トリガーとして動作する (必ずGUIでエントリポイントと関数名を揃える)
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

    # if 'overtime_lp' in schedule_input:
    #     print(f"--- [{run_id_main}] 残業時間最適配分を開始 ---", file=sys.stderr)
    #     current_full_result['overtime_result'] = solve_overtime_lp(current_full_result, schedule_input.get('overtime_lp', {}))
    #     print(f"--- [{run_id_main}] 残業時間最適配分を終了 ---", file=sys.stderr)
    # else:
    #     add_log(current_full_result, 'info', f"[{run_id_main}] 入力データに overtime_lp セクションが存在しないため、残業配分処理をスキップします。")
    #     current_full_result['overtime_result'] = {'status': 'NOT_REQUESTED', 'message': '残業データが入力ファイルにありませんでした。', 'run_id': run_id_main}

    # --- GCSへの保存処理 ---
    try:
        result_json_string = json.dumps(current_full_result, indent=2, ensure_ascii=False)
        
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        
        # オブジェクト名（ファイル名） (例: prefix + run_id + .json)
        # run_id_main にはマイクロ秒まで含めているので、ほぼ一意になる
        object_name = f"{GCS_OBJECT_PREFIX}{run_id_main}_solution.json"
        
        blob = bucket.blob(object_name)
        blob.upload_from_string(
            result_json_string,
            content_type='application/json'
        )
        gcs_path = f"gs://{GCS_BUCKET_NAME}/{object_name}"
        add_log(current_full_result, 'info', f"[{run_id_main}] 結果JSONをGCSに保存成功: {gcs_path}")
        print(f"結果をGCSに保存しました: {gcs_path}", file=sys.stderr)
        current_full_result["gcs_output_path"] = gcs_path # レスポンスにもパスを含める

    except Exception as e:
        error_message_gcs = f"[{run_id_main}] GCSへの結果保存中にエラー: {str(e)}"
        add_log(current_full_result, 'errors', error_message_gcs)
        print(error_message_gcs, file=sys.stderr)
        # エラーが発生しても、HTTPレスポンスは返す
        current_full_result["gcs_save_error"] = str(e)

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

    # if 'overtime_lp' in schedule_input:
    #     print(f"--- [{run_id_main}] 残業時間最適配分を開始 ---", file=sys.stderr)
    #     _local_full_result_for_testing_only['overtime_result'] = solve_overtime_lp(_local_full_result_for_testing_only, schedule_input.get('overtime_lp', {}))
    #     print(f"--- [{run_id_main}] 残業時間最適配分を終了 ---", file=sys.stderr)
    # else:
    #     add_log(_local_full_result_for_testing_only, 'info', f"[{run_id_main}] 入力データに overtime_lp セクションが存在しないため、残業配分処理をスキップします。")
    #     _local_full_result_for_testing_only['overtime_result'] = {'status': 'NOT_REQUESTED', 'message': '残業データが入力ファイルにありませんでした。', 'run_id': run_id_main}

    add_log(_local_full_result_for_testing_only, 'info', f"[{run_id_main}] ローカル実行終了")
    
    # ★ 最終的なJSON結果のみを標準出力に出力
    print(json.dumps(_local_full_result_for_testing_only, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    local_main()
