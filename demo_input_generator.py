import json
import random
import datetime

# --- 設定パラメータ ---
NUM_FACILITIES = 50  # 問題文の「50棟の施設」より
NUM_EMPLOYEES = 120  # 例: 施設数の1.5～3倍程度が良いでしょう
PLANNING_START_DATE_STR = "2024-07-01"  # 計画開始日
NUM_DAYS_IN_PLANNING_PERIOD = 7      # 例: 1週間 (7, 14, 30など)
DAYS_OF_WEEK_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_CONSECUTIVE_WORK_DAYS_RANGE = (4, 6) # 連続勤務日数の上限（範囲）
TIME_LIMIT_SEC = 180                     # ソルバーの計算時間制限
CLEANING_SHIFT_START_HOUR = 10
CLEANING_SHIFT_END_HOUR = 15

# 従業員関連の範囲設定
COST_PER_HOUR_RANGE = (1200.0, 2500.0)  # 時給（例: 円）
NUM_PREFERRED_FACILITIES_RANGE = (1, 5) # 従業員が希望する施設数の範囲
AVAILABILITY_SLOTS_PER_DAY_RANGE = (0, 2) # 1日の勤務可能時間帯の数（0は非番）
AVAILABILITY_START_HOUR_RANGE = (6, 15)   # 勤務開始可能時間の範囲 (例: 6時～15時)
AVAILABILITY_DURATION_HOURS_RANGE = (4, 10) # 1つの勤務時間帯の長さの範囲
CONTRACT_MAX_DAYS_PER_WEEK_RANGE = (3, 5)   # 週の契約最大労働日数
CONTRACT_MAX_HOURS_PER_DAY_RANGE = (6, 10)    # 1日の契約最大労働時間

# 残業関連の範囲設定
TOTAL_OVERTIME_HOURS_RANGE = (50, 200) # 計画期間中の総残業時間の目標範囲
OVERTIME_COST_MULTIPLIER_RANGE = (1.25, 2.0) # 通常時給に対する残業時給の倍率
MAX_OVERTIME_HOURS_PER_EMPLOYEE_RANGE = (5, 15) # 従業員1人あたりの最大残業時間（計画期間中）

# 清掃タスク関連の範囲設定
CLEANING_TASKS_PER_DAY_RANGE = (10, 60) # 1日あたりの清掃タスク数の範囲
DEFAULT_CLEANING_TASKS_PER_DAY_OF_WEEK_RANGE = (15, 50) # 曜日ごとのデフォルトタスク数

# --- ヘルパー関数 ---
def format_time(hour):
    return f"{hour:02d}:00"

def generate_input_data():
    data = {"settings": {}, "facilities": [], "employees": [], "overtime_lp": {}}

    # --- Settings ---
    data["settings"]["planning_start_date"] = PLANNING_START_DATE_STR
    data["settings"]["num_days_in_planning_period"] = NUM_DAYS_IN_PLANNING_PERIOD
    data["settings"]["days_of_week_order"] = DAYS_OF_WEEK_ORDER
    data["settings"]["max_consecutive_work_days"] = random.randint(*MAX_CONSECUTIVE_WORK_DAYS_RANGE)
    data["settings"]["time_limit_sec"] = TIME_LIMIT_SEC
    data["settings"]["hours_in_day"] = 24
    data["settings"]["cleaning_shift_start_hour"] = CLEANING_SHIFT_START_HOUR
    data["settings"]["cleaning_shift_end_hour"] = CLEANING_SHIFT_END_HOUR

    # --- Facilities ---
    facility_ids = []
    for i in range(NUM_FACILITIES):
        facility_id = f"F{i+1:03d}" # 例: F001, F002 ... F050
        facility_ids.append(facility_id)
        data["facilities"].append({
            "id": facility_id,
            "cleaning_capacity_tasks_per_hour_per_employee": random.randint(3, 8)
        })

    # --- Employees ---
    employee_main_list_for_overtime = []
    for i in range(NUM_EMPLOYEES):
        emp_id = f"E{i+1:03d}" # 例: E001, E002 ... E100
        cost_per_hour = round(random.uniform(*COST_PER_HOUR_RANGE), 2)
        
        num_prefs = random.randint(*NUM_PREFERRED_FACILITIES_RANGE)
        num_prefs = min(num_prefs, len(facility_ids)) # 希望施設数が実在施設数を超えないように
        preferred_facilities = random.sample(facility_ids, num_prefs)

        availability = []
        for day_name in DAYS_OF_WEEK_ORDER:
            num_slots_today = random.randint(*AVAILABILITY_SLOTS_PER_DAY_RANGE)
            for _ in range(num_slots_today):
                start_hour = random.randint(*AVAILABILITY_START_HOUR_RANGE)
                duration = random.randint(*AVAILABILITY_DURATION_HOURS_RANGE)
                end_hour = start_hour + duration
                end_hour = min(end_hour, 23) # 終了時間は23時を上限とする (23:00は23時台の終わりまでを意味すると解釈)
                
                # 開始時間 < 終了時間であり、最低1時間のスロットであることを保証
                if end_hour <= start_hour:
                    end_hour = start_hour + 1 
                end_hour = min(end_hour, 23) # 調整後の再上限設定

                if start_hour < end_hour: # 有効なスロットのみ追加
                    availability.append({
                        "day_of_week": day_name,
                        "start_time": format_time(start_hour),
                        "end_time": format_time(end_hour)
                    })
        
        # 従業員が全く勤務可能日がない場合を避けるためのフォールバック
        if not availability:
            day_name = random.choice(DAYS_OF_WEEK_ORDER)
            start_hour = random.randint(8, 12) 
            duration = random.randint(4, 8)
            end_hour = min(start_hour + duration, 23)
            if start_hour < end_hour: # just in case
                 availability.append({
                    "day_of_week": day_name,
                    "start_time": format_time(start_hour),
                    "end_time": format_time(end_hour)
                })

        employee_data = {
            "id": emp_id,
            "cost_per_hour": cost_per_hour,
            "preferred_facilities": preferred_facilities,
            "availability": availability,
            "contract_max_days_per_week": random.randint(*CONTRACT_MAX_DAYS_PER_WEEK_RANGE),
            "contract_max_hours_per_day": random.randint(*CONTRACT_MAX_HOURS_PER_DAY_RANGE)
        }
        data["employees"].append(employee_data)
        employee_main_list_for_overtime.append({"id": emp_id, "base_cost": cost_per_hour})

    # --- Overtime LP ---
    data["overtime_lp"]["total_overtime_hours"] = random.randint(*TOTAL_OVERTIME_HOURS_RANGE)
    overtime_employees = []
    for emp_info in employee_main_list_for_overtime:
        overtime_cost = round(emp_info["base_cost"] * random.uniform(*OVERTIME_COST_MULTIPLIER_RANGE), 2)
        overtime_employees.append({
            "id": emp_info["id"],
            "overtime_cost": overtime_cost,
            "max_overtime": random.randint(*MAX_OVERTIME_HOURS_PER_EMPLOYEE_RANGE)
        })
    data["overtime_lp"]["employees"] = overtime_employees

    return data

def generate_cleaning_tasks_data(settings_data, facilities_data):
    cleaning_tasks = {}
    start_date_obj = datetime.datetime.strptime(settings_data["planning_start_date"], "%Y-%m-%d").date()
    num_days = settings_data["num_days_in_planning_period"]
    
    all_dates_in_period = [start_date_obj + datetime.timedelta(days=i) for i in range(num_days)]

    for facility in facilities_data:
        facility_id = facility["id"]
        cleaning_tasks[facility_id] = {}
        
        # 特定の日付ごとのタスクを生成
        tasks_by_day_of_week = {day: {} for day in DAYS_OF_WEEK_ORDER}

        for date_obj in all_dates_in_period:
            day_name = DAYS_OF_WEEK_ORDER[date_obj.weekday()] # datetimeのweekday()は月曜=0
            date_str = date_obj.strftime("%Y-%m-%d")
            tasks_by_day_of_week[day_name][date_str] = random.randint(*CLEANING_TASKS_PER_DAY_RANGE)
        
        for day_name_key, date_tasks_map in tasks_by_day_of_week.items():
            if date_tasks_map: # その曜日に該当する日付がある場合のみ追加
                 cleaning_tasks[facility_id][day_name_key] = date_tasks_map

        # 曜日ごとのデフォルトタスクを生成（オプション）
        if random.choice([True, False]): # ランダムでデフォルトタスクを追加するか決定
            cleaning_tasks[facility_id]["default_tasks_for_day_of_week"] = {}
            for day_name in DAYS_OF_WEEK_ORDER:
                cleaning_tasks[facility_id]["default_tasks_for_day_of_week"][day_name] = \
                    random.randint(*DEFAULT_CLEANING_TASKS_PER_DAY_OF_WEEK_RANGE)
                    
    return cleaning_tasks

if __name__ == "__main__":
    # input_data.json を生成
    input_data_content = generate_input_data()
    output_input_filename = "generated_input_data.json"
    with open(output_input_filename, "w", encoding="utf-8") as f:
        json.dump(input_data_content, f, indent=2, ensure_ascii=False)
    print(f"'{output_input_filename}' を生成しました。")

    # cleaning_tasks.json を生成 (input_dataのsettingsとfacilities情報が必要)
    cleaning_tasks_content = generate_cleaning_tasks_data(
        input_data_content["settings"], 
        input_data_content["facilities"]
    )
    output_cleaning_filename = "generated_cleaning_tasks.json"
    with open(output_cleaning_filename, "w", encoding="utf-8") as f:
        json.dump(cleaning_tasks_content, f, indent=2, ensure_ascii=False)
    print(f"'{output_cleaning_filename}' を生成しました。")