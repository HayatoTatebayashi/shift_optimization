import json
import pandas as pd
import datetime
import os # ファイルパス操作用

OUTPUT_DIR = "visualization_output" # CSVファイルを出力するディレクトリ

def ensure_output_dir():
    """出力ディレクトリが存在しない場合は作成する"""
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

def load_json_file(filepath):
    """JSONファイルを複数のエンコーディングで読み込み試行する"""
    encodings_to_try = ['utf-8-sig', 'utf-8', 'utf-16'] # BOM付きUTF-8を最初に試す
    for encoding in encodings_to_try:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                print(f"情報: ファイル '{filepath}' をエンコーディング '{encoding}' で読み込み試行...")
                data = json.load(f)
                print(f"情報: ファイル '{filepath}' をエンコーディング '{encoding}' で読み込み成功。")
                return data
        except UnicodeDecodeError:
            print(f"情報: ファイル '{filepath}' のエンコーディング '{encoding}' でのデコードに失敗。")
            continue # 次のエンコーディングを試す
        except FileNotFoundError:
            print(f"エラー: ファイル '{filepath}' が見つかりません。")
            return None
        except json.JSONDecodeError:
            print(f"エラー: ファイル '{filepath}' のJSON形式が正しくありません (エンコーディング: {encoding})。")
            return None # JSON形式エラーの場合は他のエンコーディングを試しても無駄なので終了
        except Exception as e:
            print(f"エラー: ファイル '{filepath}' の読み込み中に予期せぬエラーが発生しました (エンコーディング: {encoding}): {e}")
            return None # その他の予期せぬエラー

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
    if not cleaning_tasks_data: print("エラー: 'cleaning_tasks_input' が入力データに含まれていません。"); 

    print(f"\n--- 解答データ ({solution_file}) 読み込み ---")
    solution_data = load_json_file(solution_file)

    print("\n--- シフトアサイン表 生成中 ---")
    if solution_data:
        assignments_df = create_shift_assignments_df(solution_data, input_schedule_data)
        if not assignments_df.empty:
            save_df_to_csv(assignments_df, "shift_assignments.csv", index=True)
        else:
            print("シフトアサインデータから有効なDataFrameを作成できませんでした。")
    else:
        print(f"{solution_file} が読み込めなかったため、シフトアサイン表は生成されません。")

    print("\n--- 施設別 清掃件数表 生成中 ---")
    if cleaning_tasks_data:
        cleaning_tasks_df = create_cleaning_tasks_df(cleaning_tasks_data, input_schedule_data)
        if not cleaning_tasks_df.empty:
            save_df_to_csv(cleaning_tasks_df, "cleaning_tasks_per_facility.csv", index=True)
        else:
            print("清掃タスクデータから有効なDataFrameを作成できませんでした。")
    else:
        print("清掃タスクデータがないため、施設別清掃件数表は生成されません。")

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