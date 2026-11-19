# Judge protocol

- 用**不同模型**做评委，不要用写代码的那个模型。
- 盲评：不要告诉评委模型名，也不要给它 agent 的自我评分。
- 评委只看：任务、diff、`report.json`、证据、rubric。
- 每个维度必须引用证据；找不到证据就给 0。
- 任一硬门失败，总分直接 0。
- 输出 JSON：

```json
{
  "score": 0,
  "dimensions": {
    "correctness": 0,
    "evidence": 0,
    "scope": 0
  },
  "notes": "引用证据，说明扣分原因"
}
```
