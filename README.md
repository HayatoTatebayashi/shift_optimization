# シフトスケジューリング最適化ソルバー

従業員のシフトスケジュールと残業時間を最適化するPythonベースのソルバーです。OR-Tools CP-SATとHiGHS LPを使用して、複雑な制約条件下での最適なスケジューリングを実現します。

## 機能

- **シフトスケジューリング (OR-Tools CP-SAT)**
  - 複数施設の24時間対応
  - 清掃タスクの最適配分
  - 従業員の希望勤務時間・施設の考慮
  - 労働規制の遵守（最大勤務時間、連続勤務制限等）
  - 総人件費の最小化

- **残業時間最適配分 (HiGHS LP)**
  - 必要残業時間の効率的な配分
  - 個人別の残業上限考慮
  - 総残業コストの最小化

## 必要条件

- Python 3.8以上
- OR-Tools
- HiGHS

```bash
pip install ortools highs
```

## 使用方法

1. 入力データの準備:
```bash
python demo_input_generator.py
```

2. ソルバーの実行:
```bash
python solve.py generated_input_data.json generated_cleaning_tasks.json > solution.json
```

## 入力データ形式

### シフトスケジューリング (generated_input_data.json)
```json
{
  "settings": {
    "planning_start_date": "2024/01/01",
    "cleaning_shift_start_hour": 9,
    "cleaning_shift_end_hour": 17
  },
  "facilities": [
    {
      "id": "F1",
      "name": "本社ビル",
      "cleaning_capacity_tasks_per_hour_per_employee": 2
    }
  ],
  "employees": [
    {
      "id": "E1",
      "name": "山田太郎",
      "cost_per_hour": 1000,
      "preferred_facilities": ["F1"],
      "availability": {
        "Mon": {"start": 9, "end": 17},
        "Tue": {"start": 9, "end": 17}
      }
    }
  ]
}
```

### 清掃タスク (generated_cleaning_tasks.json)
```json
{
  "tasks": [
    {
      "facility_id": "F1",
      "date": "2024/01/01",
      "num_tasks": 10
    }
  ]
}
```

## 出力形式

```json
{
  "schedule_result": {
    "status": "OK",
    "objective": 195000,
    "assignments": [
      {
        "employee_id": "E1",
        "facility_id": "F1",
        "date": "2024/01/01",
        "hours": [9, 10, 11, 12, 13, 14, 15, 16]
      }
    ]
  },
  "overtime_result": {
    "status": "OK",
    "objective": 72000,
    "allocation": [
      {
        "id": "E1",
        "overtime_hours": 8.0
      }
    ]
  }
}
```

## 制約条件

### ハード制約
- 従業員の勤務可能時間
- 同時に複数施設での勤務不可
- 必要最低人数の充足

### ソフト制約（ペナルティ付き）
- 連続勤務日数
- 週間勤務日数
- 1日の勤務時間
- スタッフ不足

## ライセンス

MITライセンス

## 貢献

1. このリポジトリをフォーク
2. 新しいブランチを作成 (`git checkout -b feature/amazing_feature`)
3. 変更をコミット (`git commit -am 'Add amazing feature'`)
4. ブランチにプッシュ (`git push origin feature/amazing_feature`)
5. プルリクエストを作成

## 開発者

- 作成者: Hayato Tatebayashi
- E-mail: your.email@example.com
