import json
import pandas as pd
import datetime
import os
import math # ★ この行を追加

HOURS_IN_DAY = 24 # solve_new.py と合わせる
OUTPUT_DIR = "visualization_output" # CSVファイルを出力するディレクトリ

def ensure_output_dir():
    """出力ディレクトリが存在しない場合は作成する"""
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

def load_json_file(filepath):
    encodings_to_try = ['utf-8-sig', 'utf-8', 'utf-16']
    for encoding in encodings_to_try:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                print(f"情報: ファイル '{filepath}' をエンコーディング '{encoding}' で読み込み試行...")
                data = json.load(f)
                print(f"情報: ファイル '{filepath}' をエンコーディング '{encoding}' で読み込み成功。")
                return data
        except UnicodeDecodeError:
            print(f"情報: ファイル '{filepath}' のエンコーディング '{encoding}' でのデコードに失敗。")
            continue
        except FileNotFoundError:
            print(f"エラー: ファイル '{filepath}' が見つかりません。")
            return None
        except json.JSONDecodeError:
            print(f"エラー: ファイル '{filepath}' のJSON形式が正しくありません (エンコーディング: {encoding})。")
            return None
        except Exception as e:
            print(f"エラー: ファイル '{filepath}' の読み込み中に予期せぬエラーが発生しました (エンコーディング: {encoding}): {e}")
            return None
    print(f"エラー: ファイル '{filepath}' をサポートされているエンコーディングで読み込めませんでした。")
    return None


def save_df_to_csv(df, filename, index=True):
    """DataFrameをCSVファイルに保存する"""
    filepath = os.path.join(OUTPUT_DIR, filename)
    try:
        df.to_csv(filepath, index=index, encoding='utf-8-sig')
        print(f"'{filepath}' にCSVファイルとして保存しました。")
    except Exception as e:
        print(f"エラー: '{filepath}' の保存中にエラーが発生しました: {e}")


def create_shift_assignments_df(solution_data, input_schedule_data):
    """シフトアサイン結果のDataFrameを作成する"""
    if not solution_data or 'schedule_result' not in solution_data or \
       not solution_data['schedule_result'] or 'assignments' not in solution_data['schedule_result']:
        print("シフトアサインデータが見つかりません。")
        return pd.DataFrame()

    assignments = solution_data['schedule_result']['assignments']
    if not assignments:
        print("有効なシフトアサインがありません。")
        return pd.DataFrame()

    settings = input_schedule_data.get('settings', {})
    start_date_str = settings.get('planning_start_date')
    num_days = settings.get('num_days_in_planning_period')
    days_of_week_order = settings.get('days_of_week_order', ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])

    if not start_date_str or not num_days:
        print("入力データから日付情報を取得できませんでした。")
        return pd.DataFrame()

    try:
        start_date_obj = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        print(f"日付形式エラー: {start_date_str}")
        return pd.DataFrame()

    dates = [(start_date_obj + datetime.timedelta(days=i)) for i in range(num_days)]
    date_columns = [f"{d.strftime('%Y-%m-%d')}\n({days_of_week_order[d.weekday()]})" for d in dates]

    employee_ids = sorted(list(set(assign['employee_id'] for assign in assignments)))
    if not employee_ids:
        employee_ids = sorted([emp['id'] for emp in input_schedule_data.get('employees', [])])
    if not employee_ids:
        print("従業員情報が見つかりません。")
        return pd.DataFrame()

    assignment_df_data_dict = {col: [""] * len(employee_ids) for col in date_columns}
    assignment_df = pd.DataFrame(assignment_df_data_dict, index=employee_ids)
    assignment_df.index.name = "従業員ID"

    for assign in assignments:
        emp_id = assign['employee_id']
        assign_date_str = assign['date']
        try:
            assign_date_obj = datetime.datetime.strptime(assign_date_str, "%Y-%m-%d").date()
        except ValueError:
            print(f"アサインの日付形式エラー: {assign_date_str} (従業員: {emp_id})")
            continue

        col_name = f"{assign_date_obj.strftime('%Y-%m-%d')}\n({days_of_week_order[assign_date_obj.weekday()]})"
        
        if col_name in assignment_df.columns and emp_id in assignment_df.index:
            facility_id = assign['facility_id']
            start_hour = assign['start_hour']
            end_hour = assign['end_hour']
            assign_detail = f"{facility_id} [{start_hour:02d}-{end_hour:02d}]"
            
            current_cell_value = assignment_df.loc[emp_id, col_name]
            if not current_cell_value:
                assignment_df.loc[emp_id, col_name] = assign_detail
            else:
                assignment_df.loc[emp_id, col_name] += f"\n{assign_detail}"
        else:
            print(f"警告(シフト): アサインデータの不整合 emp_id={emp_id}, date_col='{col_name}'")
    return assignment_df

def create_cleaning_tasks_df(cleaning_tasks_data, input_schedule_data):
    """施設の清掃件数のDataFrameを作成する"""
    if not cleaning_tasks_data:
        print("清掃タスクデータが見つかりません。")
        return pd.DataFrame()

    settings = input_schedule_data.get('settings', {})
    start_date_str = settings.get('planning_start_date')
    num_days = settings.get('num_days_in_planning_period')
    days_of_week_order = settings.get('days_of_week_order', ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])

    if not start_date_str or not num_days:
        print("入力データから日付情報を取得できませんでした。")
        return pd.DataFrame()
        
    try:
        start_date_obj = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        print(f"日付形式エラー: {start_date_str}")
        return pd.DataFrame()

    dates = [(start_date_obj + datetime.timedelta(days=i)) for i in range(num_days)]
    date_columns = [f"{d.strftime('%Y-%m-%d')}\n({days_of_week_order[d.weekday()]})" for d in dates]

    facility_ids = sorted([fac.get('id') for fac in input_schedule_data.get('facilities', []) if fac.get('id') in cleaning_tasks_data])
    if not facility_ids:
        facility_ids = sorted(list(cleaning_tasks_data.keys()))

    if not facility_ids:
        print("清掃タスクが設定されている施設がありません。")
        return pd.DataFrame()

    task_df_data_dict = {col: [""] * len(facility_ids) for col in date_columns}
    task_df = pd.DataFrame(task_df_data_dict, index=facility_ids)
    task_df.index.name = "施設ID"


    for fac_id in facility_ids:
        if fac_id not in cleaning_tasks_data:
             print(f"警告(清掃タスク): 施設ID '{fac_id}' の清掃タスクデータが cleaning_tasks_data に見つかりません。")
             continue
        daily_tasks_by_dow = cleaning_tasks_data[fac_id]
        for day_idx, date_obj in enumerate(dates):
            date_str_key = date_obj.strftime("%Y-%m-%d")
            dow_str_key = days_of_week_order[date_obj.weekday()]
            col_name = date_columns[day_idx]

            tasks_for_date = ""
            if dow_str_key in daily_tasks_by_dow:
                if isinstance(daily_tasks_by_dow[dow_str_key], dict) and date_str_key in daily_tasks_by_dow[dow_str_key]:
                    tasks_for_date = daily_tasks_by_dow[dow_str_key][date_str_key]
                elif "default_tasks_for_day_of_week" in daily_tasks_by_dow and \
                     isinstance(daily_tasks_by_dow["default_tasks_for_day_of_week"], dict) and \
                     dow_str_key in daily_tasks_by_dow["default_tasks_for_day_of_week"]:
                    tasks_for_date = daily_tasks_by_dow["default_tasks_for_day_of_week"][dow_str_key]
                    tasks_for_date = f"{tasks_for_date} (def)"

            if fac_id in task_df.index and col_name in task_df.columns:
                 task_df.loc[fac_id, col_name] = tasks_for_date
            else:
                print(f"警告(清掃タスク): DataFrameへのアクセスエラー fac_id={fac_id}, col_name='{col_name}'")
    return task_df

def create_facility_cleaning_capacity_df(input_schedule_data):
    """施設の清掃能力のDataFrameを作成する"""
    if 'facilities' not in input_schedule_data or not input_schedule_data['facilities']:
        print("施設データが見つかりません。")
        return pd.DataFrame()

    facilities_info = []
    for facility in input_schedule_data['facilities']:
        facilities_info.append({
            "施設ID": facility.get('id', 'N/A'),
            "1時間あたり清掃可能数": facility.get('cleaning_capacity_tasks_per_hour_per_employee', 'N/A')
        })
    
    if not facilities_info:
        print("表示する施設情報がありません。")
        return pd.DataFrame()
    return pd.DataFrame(facilities_info)

def create_employee_availability_request_df(input_schedule_data):
    """従業員のシフトリクエスト(勤務可能時間)のDataFrameを作成する"""
    if 'employees' not in input_schedule_data or not input_schedule_data['employees']:
        print("従業員データが見つかりません。")
        return pd.DataFrame()

    employees = input_schedule_data['employees']
    settings = input_schedule_data.get('settings', {})
    start_date_str = settings.get('planning_start_date')
    num_days = settings.get('num_days_in_planning_period')
    days_of_week_order = settings.get('days_of_week_order', ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])

    if not start_date_str or not num_days:
        print("入力データから日付情報を取得できませんでした。")
        return pd.DataFrame()
    try:
        start_date_obj = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        print(f"日付形式エラー: {start_date_str}")
        return pd.DataFrame()

    dates = [(start_date_obj + datetime.timedelta(days=i)) for i in range(num_days)]
    date_columns = [f"{d.strftime('%Y-%m-%d')}\n({days_of_week_order[d.weekday()]})" for d in dates]

    employee_ids = sorted([emp['id'] for emp in employees])
    if not employee_ids:
        print("従業員IDリストを作成できませんでした。")
        return pd.DataFrame()

    availability_df_data_dict = {col: [""] * len(employee_ids) for col in date_columns}
    availability_df = pd.DataFrame(availability_df_data_dict, index=employee_ids)
    availability_df.index.name = "従業員ID"

    for emp_data in employees:
        emp_id = emp_data['id']
        if emp_id not in availability_df.index:
            continue
        
        availability_by_day_of_week = {day: [] for day in days_of_week_order}
        for slot in emp_data.get('availability', []):
            dow = slot.get('day_of_week')
            start_time = slot.get('start_time')
            end_time = slot.get('end_time')
            if dow and start_time and end_time:
                availability_by_day_of_week[dow].append(f"{start_time}-{end_time}")

        for day_idx, date_obj in enumerate(dates):
            dow_str_key = days_of_week_order[date_obj.weekday()]
            col_name = date_columns[day_idx] # 正しい列名
            
            if dow_str_key in availability_by_day_of_week and availability_by_day_of_week[dow_str_key]:
                availability_df.loc[emp_id, col_name] = "\n".join(availability_by_day_of_week[dow_str_key])
            # else: # リクエストがない日は空文字のまま
                # availability_df.loc[emp_id, col_name] = "-" # またはハイフンなど

    return availability_df


def create_facility_coverage_status_df(solution_data, input_schedule_data, cleaning_tasks_data):
    """施設の常駐義務充足状況のDataFrameを作成する"""
    if 'facilities' not in input_schedule_data or not input_schedule_data['facilities']:
        print("施設データが見つかりません。")
        return pd.DataFrame()
    if not solution_data or 'schedule_result' not in solution_data or \
       not solution_data['schedule_result'] or 'assignments' not in solution_data['schedule_result']:
        print("シフトアサインデータが見つかりません。常駐状況は確認できません。")
        return pd.DataFrame() # アサインがないと充足状況は不明

    facilities = input_schedule_data['facilities']
    assignments = solution_data['schedule_result']['assignments']
    settings = input_schedule_data.get('settings', {})
    start_date_str = settings.get('planning_start_date')
    num_days = settings.get('num_days_in_planning_period')
    days_of_week_order = settings.get('days_of_week_order', ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    cleaning_start_h = settings.get('cleaning_shift_start_hour', 10)
    cleaning_end_h = settings.get('cleaning_shift_end_hour', 15)

    if not start_date_str or not num_days:
        print("入力データから日付情報を取得できませんでした。")
        return pd.DataFrame()
    try:
        start_date_obj = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        print(f"日付形式エラー: {start_date_str}")
        return pd.DataFrame()

    dates = [(start_date_obj + datetime.timedelta(days=i)) for i in range(num_days)]
    date_columns = [f"{d.strftime('%Y-%m-%d')}\n({days_of_week_order[d.weekday()]})" for d in dates]

    facility_ids = sorted([f['id'] for f in facilities])
    if not facility_ids:
        print("施設IDリストを作成できませんでした。")
        return pd.DataFrame()

    coverage_df_data_dict = {col: [""] * len(facility_ids) for col in date_columns}
    coverage_df = pd.DataFrame(coverage_df_data_dict, index=facility_ids)
    coverage_df.index.name = "施設ID"

    # 日付、施設、時間ごとの実際のアサイン人数を事前に集計
    actual_staffing = {} # (date_str, facility_id, hour) -> count
    for assign in assignments:
        assign_date_str = assign['date']
        facility_id = assign['facility_id']
        for hour in range(assign['start_hour'], assign['end_hour']):
            key = (assign_date_str, facility_id, hour)
            actual_staffing[key] = actual_staffing.get(key, 0) + 1

    for fac_data in facilities:
        fac_id = fac_data['id']
        if fac_id not in coverage_df.index:
            continue
        
        cleaning_capacity_per_hr = fac_data.get('cleaning_capacity_tasks_per_hour_per_employee', 1)
        if cleaning_capacity_per_hr <= 0: cleaning_capacity_per_hr = 1
        cleaning_hours_duration = cleaning_end_h - cleaning_start_h

        for day_idx, date_obj in enumerate(dates):
            date_str_key = date_obj.strftime("%Y-%m-%d")
            col_name = date_columns[day_idx]
            
            shortage_details = []
            # この日のこの施設の清掃タスク数を取得 (visualize_data.py内での get_cleaning_tasks_for_day_facility 相当)
            daily_cleaning_tasks = 0
            if cleaning_tasks_data and fac_id in cleaning_tasks_data:
                fac_task_data = cleaning_tasks_data[fac_id]
                dow_str_key = days_of_week_order[date_obj.weekday()]
                if dow_str_key in fac_task_data and date_str_key in fac_task_data[dow_str_key]:
                     daily_cleaning_tasks = fac_task_data[dow_str_key][date_str_key]
                elif "default_tasks_for_day_of_week" in fac_task_data and dow_str_key in fac_task_data["default_tasks_for_day_of_week"]:
                     daily_cleaning_tasks = fac_task_data["default_tasks_for_day_of_week"][dow_str_key]


            for hour in range(HOURS_IN_DAY):
                required_staff_target = 1 # デフォルト
                if cleaning_start_h <= hour < cleaning_end_h: # 清掃時間
                    if cleaning_hours_duration > 0 and daily_cleaning_tasks > 0:
                        required_staff_target = max(1, math.ceil(
                            daily_cleaning_tasks / (cleaning_capacity_per_hr * cleaning_hours_duration)
                        ))
                    # else: 清掃タスク0でも最低1名は必要なので required_staff_target は 1 のまま
                
                current_staff = actual_staffing.get((date_str_key, fac_id, hour), 0)
                
                if current_staff < required_staff_target:
                    shortage = required_staff_target - current_staff
                    shortage_details.append(f"{hour:02d}:00 (不足{shortage}, 要{required_staff_target})")
            
            if not shortage_details:
                coverage_df.loc[fac_id, col_name] = "OK"
            else:
                coverage_df.loc[fac_id, col_name] = "\n".join(shortage_details)
                
    return coverage_df


if __name__ == "__main__":
    ensure_output_dir()

    input_file = "generated_combined_input_data.json"
    solution_file = "solution.json"

    print(f"--- 入力データ ({input_file}) 読み込み ---")
    combined_input = load_json_file(input_file)
    if not combined_input: exit()
    
    input_schedule_data = combined_input.get("schedule_input")
    cleaning_tasks_data = combined_input.get("cleaning_tasks_input")

    if not input_schedule_data: print("エラー: 'schedule_input' が入力データに含まれていません。"); exit()
    # cleaning_tasks_data は optional とする (エラーにしない)

    print(f"\n--- 解答データ ({solution_file}) 読み込み ---")
    solution_data = load_json_file(solution_file)
    # solution_data がなくても他の処理は実行

    # 1. 従業員のシフトリクエスト表
    print("\n--- 従業員シフトリクエスト表 生成中 ---")
    availability_df = create_employee_availability_request_df(input_schedule_data)
    if not availability_df.empty:
        save_df_to_csv(availability_df, "employee_availability_requests.csv", index=True)
    else:
        print("従業員シフトリクエストデータから有効なDataFrameを作成できませんでした。")

    # 2. シフトアサイン表
    print("\n--- シフトアサイン表 生成中 ---")
    if solution_data:
        assignments_df = create_shift_assignments_df(solution_data, input_schedule_data)
        if not assignments_df.empty:
            save_df_to_csv(assignments_df, "shift_assignments.csv", index=True)
        else:
            print("シフトアサインデータから有効なDataFrameを作成できませんでした。")
    else:
        print(f"{solution_file} が読み込めなかったため、シフトアサイン表は生成されません。")

    # 3. 施設の常駐義務充足状況表
    print("\n--- 施設常駐義務充足状況表 生成中 ---")
    if solution_data and cleaning_tasks_data : # solution と cleaning_tasks 両方が必要
        coverage_df = create_facility_coverage_status_df(solution_data, input_schedule_data, cleaning_tasks_data)
        if not coverage_df.empty:
            save_df_to_csv(coverage_df, "facility_coverage_status.csv", index=True)
        else:
            print("施設常駐義務充足状況データから有効なDataFrameを作成できませんでした。")
    elif not solution_data:
         print(f"{solution_file} が読み込めなかったため、施設常駐義務充足状況表は生成されません。")
    elif not cleaning_tasks_data:
         print(f"cleaning_tasks_data が読み込めなかったため、施設常駐義務充足状況表は生成されません。")


    # 4. 施設表（清掃件数）
    print("\n--- 施設別 清掃件数表 生成中 ---")
    if cleaning_tasks_data:
        cleaning_tasks_df = create_cleaning_tasks_df(cleaning_tasks_data, input_schedule_data)
        if not cleaning_tasks_df.empty:
            save_df_to_csv(cleaning_tasks_df, "cleaning_tasks_per_facility.csv", index=True)
        else:
            print("清掃タスクデータから有効なDataFrameを作成できませんでした。")
    else:
        print("清掃タスクデータがないため、施設別清掃件数表は生成されません。")

    # 5. 施設の一時間あたりの清掃可能数
    print("\n--- 施設別 1時間あたり清掃可能数 生成中 ---")
    facility_capacity_df = create_facility_cleaning_capacity_df(input_schedule_data)
    if not facility_capacity_df.empty:
        save_df_to_csv(facility_capacity_df, "facility_cleaning_capacity.csv", index=False)
    else:
        print("施設清掃能力データから有効なDataFrameを作成できませんでした。")

    # (サマリ情報のコンソール表示部分は変更なし)
    if 'employees' in input_schedule_data:
        print("\n--- 従業員情報サマリ (コンソール表示、一部) ---")
        emp_summary_list = []
        for emp in input_schedule_data['employees'][:5]:
            emp_summary_list.append({
                "ID": emp.get('id'), "時給": emp.get('cost_per_hour'),
                "希望施設数": len(emp.get('preferred_facilities', [])),
                "契約週日数": emp.get('contract_max_days_per_week'),
                "契約日時間": emp.get('contract_max_hours_per_day'),
                "勤務可能スロット数": len(emp.get('availability',[]))
            })
        if emp_summary_list: print(pd.DataFrame(emp_summary_list).to_string(index=False))
        else: print("従業員データがありません。")

    if solution_data and solution_data.get('schedule_result'):
        print("\n--- スケジュール結果サマリ (コンソール表示) ---")
        sched_res = solution_data['schedule_result']
        print(f"  ステータス: {sched_res.get('status')}")
        if 'objective' in sched_res: print(f"  目的関数値: {sched_res.get('objective'):,.2f}")
        if 'wall_time_sec' in sched_res: print(f"  計算時間: {sched_res.get('wall_time_sec'):.2f} 秒")
        if 'run_id' in sched_res: print(f"  実行ID: {sched_res.get('run_id')}")
        if 'applied_constraints_history' in solution_data and solution_data.get('applied_constraints_history'):
            print("  適用された制約の履歴:")
            for i, history_item in enumerate(solution_data['applied_constraints_history']):
                print(f"    試行 {history_item.get('retry_attempt', i)} (ID: {history_item.get('run_id')}):")
                for constraint_type, settings in history_item.get('soft_constraints_settings', {}).items():
                    print(f"      - {constraint_type}: base_penalty={settings.get('base_penalty')}, multiplier={settings.get('multiplier')}")

    if solution_data and solution_data.get('overtime_result'):
        print("\n--- 残業結果サマリ (コンソール表示) ---")
        ot_res = solution_data['overtime_result']
        print(f"  ステータス: {ot_res.get('status')}")
        if ot_res.get('status') == 'OK':
            print(f"  目的関数値 (総残業コスト): {ot_res.get('objective'):,.2f}")
            total_assigned_ot = sum(alloc.get('overtime_hours', 0) for alloc in ot_res.get('allocation', []))
            print(f"  割り当てられた総残業時間: {total_assigned_ot:.2f} 時間")

    print(f"\nCSVファイルは '{OUTPUT_DIR}' ディレクトリに出力されました。")
