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
   - 契約上の週最大勤務日数および1日最大勤務時間の厳守
   - 連続勤務日数の制限
   - 総人件費（時給ベース）の最小化

2. 残業時間の最適配分 (HiGHS LP使用)
   - 必要残業時間の割り当て
   - 個人別の上限考慮
   - 総残業コストの最小化

使用方法:
    python solve.py generated_input_data.json generated_cleaning_tasks.json > solution.json
    (generated_input_data.json と generated_cleaning_tasks.json はデータ生成スクリプトで作成されたファイル)
"""
import json
import sys
import math
import datetime
from ortools.sat.python import cp_model
from ortools.linear_solver import pywraplp

# --- グローバル定数 ---
HOURS_IN_DAY = 24
full_result = {
    'schedule_result': None,
    'overtime_result': None
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

# --- ヘルパー関数 ---

# ログ追加用のヘルパー関数
def add_log(category, message, details=None):
    return
    # """汎用ログ追加関数"""
    # log_entry = {"timestamp": datetime.datetime.now().isoformat(), "message": message}
    # if details:
    #     log_entry["details"] = details
    # if category in full_result['logs']:
    #     full_result['logs'][category].append(log_entry)
    # else:
    #     # カテゴリが存在しない場合はエラーログに記録
    #     error_log_entry = {
    #         "timestamp": datetime.datetime.now().isoformat(),
    #         "message": f"未知のログカテゴリ: {category}",
    #         "original_message": message
    #     }
    #     if details:
    #         error_log_entry["original_details"] = details
    #     full_result['logs']['errors'].append(error_log_entry)
    #     print(f"警告: 未知のログカテゴリ '{category}' が使用されました。", file=sys.stderr)

def add_model_stats_log(model_instance, category, event_message):
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
    #     elif hasattr(model_instance, 'NumVariables') and hasattr(model_instance, 'NumConstraints'): # For LP solvers
    #         stats['num_variables'] = model_instance.NumVariables()
    #         stats['num_constraints'] = model_instance.NumConstraints()
    #         model_type_str = "LpSolver" # e.g. HiGHS
    #     else:
    #         warn_msg = f'モデル統計情報を取得できませんでした: 未知のモデルタイプ {model_type_str}'
    #         add_log('warnings', warn_msg, {**log_details_base, "error_details": "Unknown model type for stats."})
    #         return # 統計が取れないのでここで終了
    #     log_details = {**log_details_base, "model_type": model_type_str, **stats}
    #     log_message = f"{event_message} - モデル統計: 変数={stats['num_variables']}, 制約={stats['num_constraints']}"
    #     add_log(category, log_message, log_details)
    # except Exception as e:
    #     err_msg = f'モデル統計情報の取得中に予期せぬエラー: {str(e)}'
    #     add_log('errors', err_msg, {**log_details_base, "error_details": str(e)})

def parse_time_to_int(time_str):
    """ "HH:MM" 形式の時間を整数 (0-23) に変換 """
    return int(time_str.split(":")[0])

def get_employee_availability_matrix(employees_data, num_total_days, days_of_week_order, planning_start_date_obj):
    """
    従業員の詳細な勤務可能時間を (emp_idx, day_idx, hour_idx) -> True/False の辞書として前処理する
    """
    availability_matrix = {} # (emp_idx, day_idx, hour_idx) -> True
    employee_id_to_idx = {emp['id']: i for i, emp in enumerate(employees_data)}

    for emp_idx, emp in enumerate(employees_data):
        for avail_slot in emp.get('availability', []):
            try:
                # 勤務可能時間のデータを取得
                day_of_week_spec = avail_slot['day_of_week'] # "Mon", "Tue", ...
                start_hour_int = parse_time_to_int(avail_slot['start_time'])
                end_hour_int = parse_time_to_int(avail_slot['end_time']) # 終了時間はその時間の開始を意味する (例: 17:00は16時台まで)

                # 曜日のインデックスを取得
                for day_idx in range(num_total_days):
                    current_date = planning_start_date_obj + datetime.timedelta(days=day_idx)
                    current_day_of_week_str = days_of_week_order[current_date.weekday()] # weekday() 月曜=0

                    # 曜日が一致する場合、時間帯をマトリックスに設定
                    if current_day_of_week_str == day_of_week_spec:
                        for hour_idx in range(start_hour_int, end_hour_int): # end_hour_int は含まない
                            # 時間帯が有効な範囲内かチェック
                            if 0 <= hour_idx < HOURS_IN_DAY:
                                availability_matrix[(emp_idx, day_idx, hour_idx)] = True
            except KeyError as e:
                add_log('warnings', f"従業員 {emp.get('id', 'N/A')} の勤務可能時間データにキーエラー: {e}", {"employee_id": emp.get('id')})
            except ValueError as e:
                add_log('warnings', f"従業員 {emp.get('id', 'N/A')} の時間関連データエラー: {e}", {"employee_id": emp.get('id')})
    return availability_matrix

def get_cleaning_tasks_for_day_facility(facility_id_str, current_date_obj, cleaning_data_json, days_of_week_order):
    """ 特定の施設・日付の清掃タスク数を取得 """
    date_str = current_date_obj.strftime("%Y-%m-%d")
    day_of_week_str = days_of_week_order[current_date_obj.weekday()]

    try:
        facility_tasks = cleaning_data_json.get(facility_id_str, {})
        # まず特定の日付のタスク数を試みる
        day_specific_tasks = facility_tasks.get(day_of_week_str, {})
        if date_str in day_specific_tasks:
            return day_specific_tasks[date_str]
        # 次に曜日ごとのデフォルトタスク数を試みる
        default_tasks = facility_tasks.get("default_tasks_for_day_of_week", {})
        if day_of_week_str in default_tasks:
            return default_tasks[day_of_week_str]
    except Exception as e:
        add_log('warnings', f"清掃タスク取得中にエラー ({facility_id_str}, {date_str}): {e}", {"facility_id": facility_id_str, "date": date_str})
    return 0 # 見つからない場合は0タスク

# ---------- 1. シフトスケジューリング (CP-SAT) ----------
def solve_schedule(schedule_input_data, cleaning_tasks_data):
    """
    シフトスケジューリングを行う関数
    :param schedule_input_data: シフトスケジューリングの入力データ
    :param cleaning_tasks_data: 清掃タスクのデータ (施設ID -> 日付 -> タスク数)
    :return: シフトスケジューリングの結果
    """

    add_log('info', "シフトスケジューリング処理開始")
    settings = schedule_input_data['settings']
    facilities_data = schedule_input_data['facilities']
    employees_data = schedule_input_data['employees']

    # --- データの前処理 ---
    num_facilities = len(facilities_data)
    F_indices = range(num_facilities)
    facility_id_to_idx = {f['id']: i for i, f in enumerate(facilities_data)}
    facility_idx_to_id = {i: f['id'] for i, f in enumerate(facilities_data)}
    
    # 従業員の数
    num_employees = len(employees_data)
    # 従業員のインデックス
    W_indices = range(num_employees)
    employee_id_to_idx = {e['id']: i for i, e in enumerate(employees_data)}
    employee_idx_to_id = {i: e['id'] for i, e in enumerate(employees_data)}

    # 計画開始日をdatetimeオブジェクトに変換
    planning_start_date_obj = datetime.datetime.strptime(settings['planning_start_date'], "%Y-%m-%d").date()
    # 計画期間の日数
    num_total_days = settings['num_days_in_planning_period']
    # 日付のインデックス
    D_indices = range(num_total_days)
    
    # 曜日の順序設定
    days_of_week_order = settings.get('days_of_week_order', ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])

    # 清掃シフトの時間帯設定
    H_indices = range(HOURS_IN_DAY)
    # 清掃シフトの開始・終了時間を整数で取得
    cleaning_start_h = settings['cleaning_shift_start_hour']
    # この時間の終了まで (例: 15時は15時台まで)
    cleaning_end_h = settings['cleaning_shift_end_hour'] 
    # 清掃シフトの時間帯の長さ
    cleaning_hours_duration = cleaning_end_h - cleaning_start_h
    
    # 従業員の勤務可能時間マトリックスを作成
    # emp_avail_matrix[(emp_idx, day_idx, hour_idx)] = True/False
    emp_avail_matrix = get_employee_availability_matrix(employees_data, num_total_days, days_of_week_order, planning_start_date_obj)
    add_log('info', "従業員の勤務可能時間マトリックス作成完了")

    # 従業員の希望施設をセットで保持 (高速なルックアップのため)
    emp_preferred_facilities_idx_sets = [
        # 従業員の希望施設IDをインデックスに変換してセットにする
        set(facility_id_to_idx[fid] for fid in emp.get('preferred_facilities', []) if fid in facility_id_to_idx)
        for emp in employees_data
    ]

    # --- モデルの初期化 ---
    model = cp_model.CpModel()
    add_log('schedule', "CP-SATモデルオブジェクト作成完了")

    # --- 決定変数 ---
    # x[f, w, d, h]: 従業員wが施設fに日dの時間hに勤務するか
    # 1時間単位での勤務を表すブール変数
    x = {}
    for f_idx in F_indices:
        for w_idx in W_indices:
            for d_idx in D_indices:
                for h_idx in H_indices:
                    x[f_idx, w_idx, d_idx, h_idx] = model.NewBoolVar(f'x_f{f_idx}_w{w_idx}_d{d_idx}_h{h_idx}')
    add_log('schedule', "決定変数 (x[f,w,d,h]) 作成完了", {"num_x_vars": len(x)})

    # works_on_day[w, d]: 従業員wが日dに1時間でも勤務するか (補助変数)
    # 従業員がその日に勤務しているかどうかを示すブール変数
    works_on_day = {}
    for w_idx in W_indices:
        for d_idx in D_indices:
            works_on_day[w_idx, d_idx] = model.NewBoolVar(f'works_w{w_idx}_d{d_idx}')
    add_log('schedule', "補助変数 (works_on_day[w,d]) 作成完了", {"num_works_on_day_vars": len(works_on_day)})

    # --- ハード制約（絶対に違反できない制約） ---
    add_log('schedule', "制約の追加開始")

    # 〇 従業員の勤務可能時間と希望施設
    for f_idx in F_indices:
        for w_idx in W_indices:
            # 希望施設でない場合は割り当て不可
            if f_idx not in emp_preferred_facilities_idx_sets[w_idx] and emp_preferred_facilities_idx_sets[w_idx]: # 希望が空ならどこでもOKと解釈しない場合
                 for d_idx in D_indices:
                    # この従業員はこの施設には入れないので、全時間帯で勤務不可にする
                    for h_idx in H_indices:
                        model.Add(x[f_idx, w_idx, d_idx, h_idx] == 0)
                    continue # この従業員はこの施設には入れないので次の従業員へ
                 
            # 勤務可能時間に基づく制約
            for d_idx in D_indices:
                for h_idx in H_indices:
                    # 勤務可能時間外は勤務不可
                    if not emp_avail_matrix.get((w_idx, d_idx, h_idx), False):
                        model.Add(x[f_idx, w_idx, d_idx, h_idx] == 0)
    add_model_stats_log(model, 'schedule', '制約の追加')                 

    # 〇 従業員は同時に1つの施設でのみ勤務可能
    for w_idx in W_indices:
        for d_idx in D_indices:
            for h_idx in H_indices:
                model.Add(sum(x[f_idx, w_idx, d_idx, h_idx] for f_idx in F_indices) <= 1)
    add_model_stats_log(model, 'schedule', '制約の追加')      

    # 〇 施設カバレッジ (清掃シフト以外と、清掃シフトの基本1名)
    # for f_idx in F_indices:
    #     facility_details = facilities_data[f_idx]
    #     # 施設の通常営業時間を取得
    #     facility_cleaning_capacity_per_hr = facility_details.get('cleaning_capacity_tasks_per_hour_per_employee', 1)
    #     # 0や負の値は避ける
    #     if facility_cleaning_capacity_per_hr <= 0: facility_cleaning_capacity_per_hr = 1 # 0や負を避ける

    #     # 施設の清掃シフト時間帯を取得
    #     for d_idx in D_indices:
    #         # 現在の日付を計算
    #         current_date = planning_start_date_obj + datetime.timedelta(days=d_idx)
            
    #         # この日のこの施設の清掃タスク数を取得
    #         daily_cleaning_tasks = get_cleaning_tasks_for_day_facility(
    #             facility_idx_to_id[f_idx], current_date, cleaning_tasks_data, days_of_week_order
    #         )
            
    #         # デフォルトは1名(清掃件数がない場合もあるが常駐制約満たすため)
    #         required_cleaning_staff_for_shift = 1 
    #         # 清掃シフトの時間帯に必要なスタッフ数を計算
    #         if cleaning_hours_duration > 0 and daily_cleaning_tasks > 0:
    #             required_cleaning_staff_for_shift = max(1, math.ceil(
    #                 daily_cleaning_tasks / (facility_cleaning_capacity_per_hr * cleaning_hours_duration)
    #             ))

    #         # 清掃シフト時間帯のスタッフ数制約
    #         for h_idx in H_indices:
    #             if cleaning_start_h <= h_idx < cleaning_end_h: # 清掃シフト時間内
    #                 model.Add(sum(x[f_idx, w_idx, d_idx, h_idx] for w_idx in W_indices) >= required_cleaning_staff_for_shift)
    #             else: # 清掃シフト時間外
    #                 # 通常時間帯でも最低1名を配置
    #                 model.Add(sum(x[f_idx, w_idx, d_idx, h_idx] for w_idx in W_indices) >= 1)
    # add_model_stats_log(model, 'schedule', '制約の追加')      

    # 〇 各日の必要人数の充足 works_on_day[w, d]を利用
    # for w_idx in W_indices:
    #     for d_idx in D_indices:
    #         # 従業員wが日dに1時間でも働いていれば works_on_day[w,d] = 1
    #         hours_worked_this_day = sum(x[f_idx, w_idx, d_idx, h_idx] for f_idx in F_indices for h_idx in H_indices)
    #         model.Add(hours_worked_this_day > 0).OnlyEnforceIf(works_on_day[w_idx, d_idx])
    #         model.Add(hours_worked_this_day == 0).OnlyEnforceIf(works_on_day[w_idx, d_idx].Not())
    # add_log('schedule', '制約の追加', {
    #     'num_variables': model.NumVariables(),
    #     'num_constraints': model.NumConstraints()
    # })        

    # 〇 契約: 1日あたりの最大労働時間
    # for w_idx in W_indices:
    #     # 従業員の契約上の最大労働時間を取得
    #     max_hours_day = employees_data[w_idx].get('contract_max_hours_per_day', HOURS_IN_DAY)
    #     for d_idx in D_indices:
    #         model.Add(sum(x[f_idx, w_idx, d_idx, h_idx] for f_idx in F_indices for h_idx in H_indices) <= max_hours_day)
    # add_log('schedule', '制約の追加', {
    #     'num_variables': model.NumVariables(),
    #     'num_constraints': model.NumConstraints()
    # })        

    # 〇 契約: 週あたりの最大労働日数
    # 計画期間が週の途中で始まる/終わる場合も考慮し、7日ごとのまとまりでチェック
    # for w_idx in W_indices:
    #     # 従業員の契約上の最大労働日数を取得
    #     max_days_week = employees_data[w_idx].get('contract_max_days_per_week', 7)
    #     # 計画期間の日数を7日ごとに分割して制約を追加
    #     for week_start_day_idx in range(0, num_total_days, 7):
    #         # 週の開始日から7日間の勤務日数をカウント
    #         days_in_this_week_segment = [
    #             works_on_day[w_idx, d_idx]
    #             for d_idx in range(week_start_day_idx, min(week_start_day_idx + 7, num_total_days))
    #         ]
    #         # 週の開始日から7日間の勤務日数が設定されている場合のみ制約を追加
    #         if days_in_this_week_segment:
    #              model.Add(sum(days_in_this_week_segment) <= max_days_week)
    # add_log('schedule', '制約の追加', {
    #     'num_variables': model.NumVariables(),
    #     'num_constraints': model.NumConstraints()
    # })        

    # 〇 最大連続勤務日数
    # max_consecutive_setting = settings.get('max_consecutive_work_days', 5)
    # # 従業員ごとに最大連続勤務日数の制約を追加
    # if max_consecutive_setting > 0 and num_total_days > max_consecutive_setting :
    #     # 各従業員について、連続勤務日数が最大を超えないように制約を追加
    #     for w_idx in W_indices:
    #         for d_idx_start in range(num_total_days - max_consecutive_setting):
    #             model.Add(sum(works_on_day[w_idx, d] for d in range(d_idx_start, d_idx_start + max_consecutive_setting + 1)) <= max_consecutive_setting)
    # add_log('schedule', '制約の追加', {
    #     'num_variables': model.NumVariables(),
    #     'num_constraints': model.NumConstraints()
    # })        

    add_log('schedule', "全ての基本制約の追加完了")
    add_model_stats_log(model, 'schedule', "基本制約追加後のモデル状態")

    # --- ソフト制約（コストとして最適化する制約） ---

    soft_penalty_terms = []
    objective_terms = []
    
    # 〇 最大連続勤務日数
    # 従業員ごとに最大連続勤務日数の設定を取得
    max_consecutive_setting = settings.get('max_consecutive_work_days', 5)
    # 従業員ごとに最大連続勤務日数のペナルティを追加
    consecutive_penalty = settings.get('consecutive_days_penalty', 50000)  # ペナルティコスト
    # 連続勤務日数の制約を追加
    if max_consecutive_setting > 0 and num_total_days > max_consecutive_setting:
        for w_idx in W_indices:
            for d_idx_start in range(num_total_days - max_consecutive_setting):
                # 連続勤務日数をカウント
                consecutive_days_worked = sum(works_on_day[w_idx, d] 
                    for d in range(d_idx_start, d_idx_start + max_consecutive_setting + 1))
                # 連続勤務日数が最大を超えた場合のペナルティを追加
                excess_consecutive = model.NewIntVar(0, max_consecutive_setting + 1, 
                    f'consecutive_excess_w{w_idx}_d{d_idx_start}')
            
            # 連続勤務日数が最大を超えたかどうかのブール変数
            is_exceeding = model.NewBoolVar(f'is_exceeding_consecutive_w{w_idx}_d{d_idx_start}')
            # 制約を追加
            # 連続勤務日数が最大を超えた場合は is_exceeding = True
            model.Add(consecutive_days_worked > max_consecutive_setting).OnlyEnforceIf(is_exceeding)
            # 連続勤務日数が最大を超えない場合は is_exceeding = False
            model.Add(consecutive_days_worked <= max_consecutive_setting).OnlyEnforceIf(is_exceeding.Not())
            # 連続勤務日数が最大を超えた場合のペナルティを追加
            model.Add(excess_consecutive == consecutive_days_worked - max_consecutive_setting).OnlyEnforceIf(is_exceeding)
            # 連続勤務日数が最大を超えない場合は excess_consecutive = 0
            model.Add(excess_consecutive == 0).OnlyEnforceIf(is_exceeding.Not())
            
            soft_penalty_terms.append(excess_consecutive * consecutive_penalty)
    add_model_stats_log(model, 'schedule', '制約の追加')

    # 〇 週あたりの最大労働日数
    weekly_days_penalty = settings.get('weekly_days_penalty', 40000)  # ペナルティコスト
    for w_idx in W_indices:
        # 従業員の契約上の最大労働日数を取得
        max_days_week = employees_data[w_idx].get('contract_max_days_per_week', 7)
        # 週ごとに勤務日数をカウント
        for week_start_day_idx in range(0, num_total_days, 7):
            # 週の開始日から7日間の勤務日数をカウント
            days_in_week = sum(works_on_day[w_idx, d_idx]
                for d_idx in range(week_start_day_idx, 
                    min(week_start_day_idx + 7, num_total_days)))
            # 週の開始日から7日間の勤務日数が設定されている場合のみ制約を追加 
            excess = model.NewIntVar(0, 7, f'weekly_excess_w{w_idx}_week{week_start_day_idx}')
            # 週の勤務日数が最大を超えた場合のペナルティを追加
            model.Add(days_in_week - max_days_week == excess)
            soft_penalty_terms.append(excess * weekly_days_penalty)
    add_model_stats_log(model, 'schedule', '制約の追加')

    # 〇 1日あたりの最大労働時間
    daily_hours_penalty = settings.get('daily_hours_penalty', 30000)  # ペナルティコスト
    for w_idx in W_indices:
        # 従業員の契約上の最大労働時間を取得
        max_hours_day = employees_data[w_idx].get('contract_max_hours_per_day', HOURS_IN_DAY)
        for d_idx in D_indices:
            # 各日の勤務時間をカウント
            hours_worked = sum(x[f_idx, w_idx, d_idx, h_idx] 
                for f_idx in F_indices for h_idx in H_indices)
            # 1日の勤務時間が最大を超えた場合のペナルティを追加
            excess = model.NewIntVar(0, HOURS_IN_DAY, f'daily_excess_w{w_idx}_d{d_idx}')
            model.Add(hours_worked - max_hours_day == excess)
            soft_penalty_terms.append(excess * daily_hours_penalty)
    add_model_stats_log(model, 'schedule', '制約の追加')

    # 〇 各日の必要人数の充足
    staff_shortage_penalty = settings.get('staff_shortage_penalty', 100000)  # ペナルティコスト
    for f_idx in F_indices:
        # 各施設の清掃能力を取得
        facility_details = facilities_data[f_idx] # facility_details をここで取得
        # 施設の清掃能力 (1時間あたりのタスク数) を取得
        facility_cleaning_capacity_per_hr = facility_details.get('cleaning_capacity_tasks_per_hour_per_employee', 1)
        # 0や負の値は避ける
        if facility_cleaning_capacity_per_hr <= 0: facility_cleaning_capacity_per_hr = 1

        for d_idx in D_indices:
            # 現在の日付を計算
            current_date = planning_start_date_obj + datetime.timedelta(days=d_idx) # current_date をここで取得
            # この日のこの施設の清掃タスク数を取得
            daily_cleaning_tasks = get_cleaning_tasks_for_day_facility( # daily_cleaning_tasks をここで取得
                facility_idx_to_id[f_idx], current_date, cleaning_tasks_data, days_of_week_order
            )

            for h_idx in H_indices:
                # ループ内で毎回 required_staff を計算する
                required_staff_target = 1  # 基本必要人数 (清掃時間外)
                if cleaning_start_h <= h_idx < cleaning_end_h: # 清掃シフト時間内
                    if cleaning_hours_duration > 0 and daily_cleaning_tasks > 0:
                        required_staff_target = max(1, math.ceil(
                            daily_cleaning_tasks / (facility_cleaning_capacity_per_hr * cleaning_hours_duration)
                        ))
                    else: # 清掃タスクがない清掃時間帯も最低1人
                        required_staff_target = 1
                
                # 施設fの時間hに必要なスタッフ数を計算
                staff_count = sum(x[f_idx, w_idx, d_idx, h_idx] for w_idx in W_indices)
                
                # 不足人数を計算するための変数 (0以上)
                shortage = model.NewIntVar(0, max(0, required_staff_target), f'staff_shortage_f{f_idx}_d{d_idx}_h{h_idx}')
                model.Add(required_staff_target - staff_count <= shortage) # staff_count が target より少ない場合、shortage は正
                                                                        # staff_count が target 以上の場合、shortage は 0 (IntVarの定義で0以上になる)

                # 厳密に不足分だけをペナルティにするなら以下のようにするか、
                # もしくは AddMaxEquality を使う (ただし、線形化が必要になる可能性)
                # model.Add(shortage >= required_staff_target - staff_count)
                # model.Add(shortage >= 0)
                # もっと簡単なのは、不足している場合にのみペナルティを課すことです
                # 例えば、bool変数 is_shortage を作り、
                # is_shortage = 1 iff required_staff_target > staff_count
                # soft_penalty_terms.append(is_shortage * staff_shortage_penalty * (required_staff_target - staff_count))
                # ただ、現在の shortage の定義でも、不足分に応じてペナルティが線形に増える形にはなっています。

                # 現在の定義 shortage = model.NewIntVar(0, len(W_indices), ...)
                # model.Add(required_staff_target - staff_count == shortage) は、
                # スタッフが多すぎる場合に shortage が負になり、IntVar の下限0と矛盾して INFEASIBLE になる可能性がある。
                # 修正: shortage >= required_staff_target - staff_count と shortage >= 0 とする。
                # もしくは、不足分を正の値として捉える。
                
                # 修正案: 不足人数を変数で表現
                # 例えば、actual_shortage = max(0, required_staff_target - staff_count) を表現する。
                actual_shortage = model.NewIntVar(0, required_staff_target, f'actual_shortage_f{f_idx}_d{d_idx}_h{h_idx}')
                # actual_shortage = max(0, required_staff_target - staff_count) を表現
                # ここで、required_staff_target - staff_count が負の場合は actual_shortage = 0
                b = model.NewBoolVar(f'is_short_f{f_idx}_d{d_idx}_h{h_idx}')

                # 制約を追加
                model.Add(required_staff_target - staff_count > 0).OnlyEnforceIf(b)
                model.Add(required_staff_target - staff_count <= 0).OnlyEnforceIf(b.Not())
                # actual_shortage の定義
                model.Add(actual_shortage == required_staff_target - staff_count).OnlyEnforceIf(b)
                model.Add(actual_shortage == 0).OnlyEnforceIf(b.Not())
                
                # ペナルティ項を追加
                soft_penalty_terms.append(actual_shortage * staff_shortage_penalty)
    add_model_stats_log(model, 'schedule', '制約の追加')

    # 〇 総人件費の最小化
    for f_idx in F_indices:
        for w_idx in W_indices:
            # 従業員のコストを取得 (デフォルトは1000)
            cost_per_hour = employees_data[w_idx].get('cost_per_hour', 1000)
            for d_idx in D_indices:
                for h_idx in H_indices:
                    # 勤務している場合はコストを加算
                    objective_terms.append(x[f_idx, w_idx, d_idx, h_idx] * cost_per_hour)
    add_model_stats_log(model, 'schedule', '制約の追加')     

    # 目的関数の更新: 通常のコストとペナルティの合計を最小化
    model.Minimize(sum(objective_terms) + sum(soft_penalty_terms))

    add_log('schedule', "目的関数設定完了")
    add_model_stats_log(model, 'schedule', "目的関数設定後のモデル状態")
    
    # --- ソルバー実行 ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = settings.get('time_limit_sec', 60) # 制限時間 (現在1800秒で設定)
    solver.parameters.log_search_progress = True # ログ出力
    solver.parameters.num_search_workers = 8 # 利用可能なコア数に応じて調整

    add_log('info', f"CP-SATソルバー実行開始 (制限時間: {solver.parameters.max_time_in_seconds}秒)")
    status = solver.Solve(model)
    status_str = CP_SOLVER_STATUS_MAP.get(status, 'UNKNOWN')
    add_log('info', f"CP-SATソルバー実行完了", {
        'status': status_str,
        'wall_time': solver.WallTime(),
        'objective': solver.ObjectiveValue() if status in [cp_model.OPTIMAL, cp_model.FEASIBLE] else None
    })

    # ステータスのマッピング
    status_map = {
        cp_model.OPTIMAL: 'OPTIMAL',
        cp_model.FEASIBLE: 'FEASIBLE',
        cp_model.INFEASIBLE: 'INFEASIBLE',
        cp_model.MODEL_INVALID: 'MODEL_INVALID',
        cp_model.UNKNOWN: 'UNKNOWN'
    }    

    # --- 結果の整形 ---
    result = {'status': status_map.get(status, 'UNKNOWN')}  # 変更箇所
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        result['objective'] = solver.ObjectiveValue()
        result['wall_time_sec'] = solver.WallTime()
        add_log('schedule', "解が見つかりました", {"objective": result['objective'], "wall_time_sec": result['wall_time_sec']})
        
        assignments = []
        # 従業員ごとに連続した勤務ブロックをまとめる
        for w_idx in W_indices:
            emp_id = employee_idx_to_id[w_idx]
            for d_idx in D_indices:
                current_date_str = (planning_start_date_obj + datetime.timedelta(days=d_idx)).strftime("%Y-%m-%d")
                for f_idx in F_indices:
                    facility_id = facility_idx_to_id[f_idx]
                    current_block_start_hour = -1
                    for h_idx in H_indices:
                        if solver.Value(x[f_idx, w_idx, d_idx, h_idx]) == 1:
                            if current_block_start_hour == -1:
                                current_block_start_hour = h_idx
                        else: # 勤務していないか、勤務が途切れた
                            if current_block_start_hour != -1: # 直前まで勤務していた
                                assignments.append({
                                    "employee_id": emp_id,
                                    "facility_id": facility_id,
                                    "date": current_date_str,
                                    "start_hour": current_block_start_hour,
                                    "end_hour": h_idx # h_idxの手前まで勤務していたので、h_idxが終了時間
                                })
                                current_block_start_hour = -1
                    if current_block_start_hour != -1: # 最終時間まで勤務していた場合
                        assignments.append({
                            "employee_id": emp_id,
                            "facility_id": facility_id,
                            "date": current_date_str,
                            "start_hour": current_block_start_hour,
                            "end_hour": HOURS_IN_DAY 
                        })
        result['assignments'] = assignments

        # 診断情報（例：従業員ごとの総勤務時間と勤務日数）
        diagnostics = {
            "hours_worked_per_employee": {},
            "days_worked_per_employee": {}
        }
        for w_idx in W_indices:
            emp_id = employee_idx_to_id[w_idx]
            total_hours = 0
            for d_idx in D_indices:
                 for f_idx in F_indices:
                    for h_idx in H_indices:
                        if solver.Value(x[f_idx, w_idx, d_idx, h_idx]) == 1:
                            total_hours +=1
            diagnostics["hours_worked_per_employee"][emp_id] = total_hours
            
            total_days = 0
            for d_idx in D_indices:
                if solver.Value(works_on_day[w_idx, d_idx]) == 1:
                    total_days +=1
            diagnostics["days_worked_per_employee"][emp_id] = total_days
        result["diagnostics"] = diagnostics
        add_log('schedule', "結果の整形完了", {"num_assignments": len(assignments)})

    else:
        result['message'] = "解が見つかりませんでした。"
        # add_log('errors', "CP-SAT: 解が見つかりませんでした。", {"status_code": status, "status_text": cp_model.OPTIMAL_STATUS_STRINGS[status]})
        if status == cp_model.INFEASIBLE:
            add_log('errors', "実行可能解が見つかりませんでした")
            return {
                'status': 'INFEASIBLE',
                'message': '制約を満たす解が存在しません'
            }
        elif status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            add_log('errors', f"ソルバーが有効な解を見つけられませんでした: {status_str}")
            return {
                'status': status_str,
                'message': 'ソルバーが有効な解を見つけられませんでした'
            }
        elif status == cp_model.MODEL_INVALID:
            add_log('errors', "モデルが無効です。定義を確認してください。")
            # print(model.Validate()) # 詳細なバリデーション (必要な場合)

            
    return result

# ---------- 2. 残業時間最適配分 (LP) ----------
def solve_overtime_lp(overtime_input_data):
    """
    残業時間の最適配分をHiGHS LPソルバーを使用して解決する関数
    残業時間の割り当てを最適化し、各従業員の残業時間を決定する。
    入力:
        overtime_input_data: 残業時間の割り当てに必要なデータを含む辞書
            - 'employees': 従業員のリスト (各従業員はID、最大残業時間、残業コストを含む)
            - 'total_overtime_hours': 必要な総残業時間
    出力:
        残業時間の割り当て結果を含む辞書
            - 'status': 解のステータス ('OK', 'INFEASIBLE', 'UNBOUNDED', 'NO_DATA', 'SOLVER_ERROR')
            - 'objective': 最小化された残業コスト (成功時のみ)
            - 'allocation': 各従業員の残業時間割り当て (成功時のみ)
            - 'message': エラーメッセージや警告 (必要に応じて)
    """

    add_log('info', "残業時間最適配分処理開始")

    # 入力データの検証
    if not overtime_input_data or not overtime_input_data.get('employees'):
        msg = '残業データが提供されていないか、従業員リストが空です。'
        add_log('warnings', msg)
        return {'status': 'NO_DATA', 'message': msg}

    # 従業員データの取得
    employees_ot_data = overtime_input_data['employees']
    total_ot_needed = overtime_input_data.get('total_overtime_hours', 0)

    # 従業員の残業データが空の場合
    if total_ot_needed <= 0:
        msg = '必要な総残業時間が0以下です。処理をスキップします。'
        add_log('info', msg)
        return {'status': 'OK', 'objective': 0, 'allocation': [], 'message': msg}

    # HiGHSソルバーの作成
    solver = _create_highs_solver("overtime_lp")
    if not solver:
        msg = 'HiGHSソルバーの作成に失敗しました。'
        add_log('errors', msg)
        return {'status': 'SOLVER_ERROR', 'message': msg}
    add_log('overtime', "HiGHSソルバーオブジェクト作成完了")

    # 決定変数: x_w = 従業員wの残業時間
    x = {}
    for emp in employees_ot_data:
        max_ot = emp.get('max_overtime', 0)
        # 従業員IDがない、または最大残業時間が0以下の場合は変数を作成しない
        if 'id' not in emp or max_ot <= 0:
            add_log('warnings', f"従業員 {emp.get('id', 'ID不明')} の残業変数は作成されません (max_overtime <= 0 または IDなし)。", emp)
            continue
        x[emp['id']] = solver.NumVar(0, max_ot, f'ot_{emp["id"]}')

    # 制約: 総残業時間の充足
    if not x: # 残業を割り当て可能な従業員がいない
        if total_ot_needed > 0:
            msg = "残業を割り当てる有効な従業員がいませんが、残業が必要です。"
            add_log('errors', msg)
            return {'status': 'INFEASIBLE', 'message': msg}
        else:
            msg = "残業を割り当てる有効な従業員がおらず、必要な残業もありません。"
            add_log('info', msg)
            return {'status': 'OK', 'objective': 0, 'allocation': [], 'message': msg}
        
    add_log('overtime', f"決定変数 (ot_従業員ID) 作成完了 (有効従業員数: {len(x)})")            

    solver.Add(sum(x.values()) == total_ot_needed)
    add_log('overtime', f"総残業時間制約 ({total_ot_needed}時間) 追加完了")

    # 目的関数: 残業コストの最小化
    objective_terms = []
    # 従業員ごとの残業コストを計算
    for emp in employees_ot_data:
        # 従業員の残業コストを取得 (デフォルトは9999)
        cost = emp.get('overtime_cost', 9999) # 高めのデフォルトコスト
        if emp['id'] in x: # 変数が存在する場合のみ
            # 残業時間変数とコストを掛け合わせて目的関数に追加
            objective_terms.append(cost * x[emp['id']])
    if objective_terms: # 目的関数が空でない場合
        solver.Minimize(sum(objective_terms))
        add_log('overtime', "目的関数 (残業コスト最小化) 設定完了")
    else: # ここには到達しないはず (xが空でない場合)
        add_log('warnings', "残業配分: 目的関数が設定されませんでした。")

    # ソルバーのパラメータ設定
    add_model_stats_log(solver, 'overtime', "LPモデル構築完了後の状態")
    add_log('info', "LPソルバー実行開始")
    status = solver.Solve()
    add_log('info', f"LPソルバー実行完了 (ステータスコード: {status})")

    # ステータスのマッピング
    if status == pywraplp.Solver.OPTIMAL or status == pywraplp.Solver.FEASIBLE:
        obj_val = solver.Objective().Value() if objective_terms else 0
        allocation = [{'id': emp_id, 'overtime_hours': var.solution_value()} for emp_id, var in x.items()]
        add_log('overtime', "解が見つかりました", {"objective": obj_val, "num_allocations": len(allocation)})
        return {'status': 'OK', 'objective': obj_val, 'allocation': allocation}
    else:
        status_map = { pywraplp.Solver.INFEASIBLE: 'INFEASIBLE', pywraplp.Solver.UNBOUNDED: 'UNBOUNDED', 
                       pywraplp.Solver.ABNORMAL: 'ABNORMAL', pywraplp.Solver.NOT_SOLVED: 'NOT_SOLVED',
                       pywraplp.Solver.MODEL_INVALID: 'MODEL_INVALID' }
        status_str = status_map.get(status, f'UNKNOWN_STATUS_{status}')
        msg = f'残業配分問題で解が見つかりませんでした (ステータス: {status_str})。'
        add_log('errors', msg, {"status_code": status, "status_text": status_str})
        return {'status': status_str, 'message': msg}

# ---------- メイン処理 ----------
def main():
    """
    メイン関数: 入力データの読み込み、シフトスケジューリングと残業時間最適配分の実行
    """

    global full_result # グローバル変数を変更するため
    add_log('info', "スクリプト実行開始", {"arguments": sys.argv})

    if len(sys.argv) < 3:
        msg = '使用方法: solve.py <input_data.json> <cleaning_tasks.json>'
        add_log('errors', msg)
        print(msg, file=sys.stderr)
        # エラーログを出力するために、ここでは exit しない
        print(json.dumps(full_result, indent=2, ensure_ascii=False))
        sys.exit(1)
    
    input_data_filepath = sys.argv[1]
    cleaning_tasks_filepath = sys.argv[2]

    try:
        with open(input_data_filepath, 'r', encoding='utf-8') as f:
            input_json_data = json.load(f)
        add_log('info', f"入力ファイル '{input_data_filepath}' の読み込み成功")
    except FileNotFoundError:
        add_log('errors', f"入力ファイル '{input_data_filepath}' が見つかりません。")
        print(json.dumps(full_result, indent=2, ensure_ascii=False))
        sys.exit(1)
    except json.JSONDecodeError as e:
        add_log('errors', f"入力ファイル '{input_data_filepath}' のJSON形式エラー: {e}")
        print(json.dumps(full_result, indent=2, ensure_ascii=False))
        sys.exit(1)

    try:
        with open(cleaning_tasks_filepath, 'r', encoding='utf-8') as f:
            cleaning_tasks_json_data = json.load(f)
        add_log('info', f"清掃タスクファイル '{cleaning_tasks_filepath}' の読み込み成功")
    except FileNotFoundError:
        add_log('errors', f"清掃タスクファイル '{cleaning_tasks_filepath}' が見つかりません。")
        print(json.dumps(full_result, indent=2, ensure_ascii=False))
        sys.exit(1)
    except json.JSONDecodeError as e:
        add_log('errors', f"清掃タスクファイル '{cleaning_tasks_filepath}' のJSON形式エラー: {e}")
        print(json.dumps(full_result, indent=2, ensure_ascii=False))
        sys.exit(1)

    # schedule_result と overtime_result を None で初期化
    full_result['schedule_result'] = None
    full_result['overtime_result'] = None

    if 'settings' in input_json_data and 'facilities' in input_json_data and 'employees' in input_json_data:
        print("--- シフトスケジューリングを開始 ---", file=sys.stderr)
        full_result['schedule_result'] = solve_schedule(input_json_data, cleaning_tasks_json_data)
        print("--- シフトスケジューリングを終了 ---", file=sys.stderr)
    else:
        msg = 'スケジューリングに必要な基本データ（settings, facilities, employees）が不足しています。'
        add_log('errors', msg)
        full_result['schedule_result'] = {'status': 'NO_DATA_ERROR', 'message': msg}

    if 'overtime_lp' in input_json_data:
        print("--- 残業時間最適配分を開始 ---", file=sys.stderr)
        full_result['overtime_result'] = solve_overtime_lp(input_json_data.get('overtime_lp', {}))
        print("--- 残業時間最適配分を終了 ---", file=sys.stderr)
    else:
        add_log('info', '入力データに overtime_lp セクションが存在しないため、残業配分処理をスキップします。')
        full_result['overtime_result'] = {'status': 'NOT_REQUESTED', 'message': '残業データが入力ファイルにありませんでした。'}

    add_log('info', "スクリプト実行終了")
    print(json.dumps(full_result, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
