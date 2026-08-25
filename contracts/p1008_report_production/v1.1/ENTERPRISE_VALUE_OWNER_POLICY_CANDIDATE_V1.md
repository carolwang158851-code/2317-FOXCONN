# Enterprise Value Owner Policy Candidate V1

狀態：`NOT_ACTIVE`。本文件僅供Owner逐項審查；所有決策均為`PENDING`，不構成交易、部位或發布指令。

完整公式、經濟理由、歷史校準、證據層級、恢復條件、hysteresis及缺值處理，以同目錄的`ENTERPRISE_VALUE_OWNER_POLICY_CANDIDATE_V1.json`為準。

| Dimension | Metric | Candidate threshold | Why this threshold | Historical evidence | Required evidence tier | Persistence | Hard blocker? | Recovery condition | Open dependency | Owner decision |
|---|---|---|---|---|---|---|---:|---|---|---|
| ROIC/WACC | ROIC spread | ≥5強；2–5創值；0–2窄幅；-2–0警戒；≤-2毀值 | 報酬須高於資金成本，2點作候選noise buffer | ROIC 21季；中位11.15%、σ 2.02點 | 嚴重狀態須T0/T1同口徑實際值 | 毀值候選2季 | Yes | spread≥2且無毀值佐證，連續2季 | Governed WACC | PENDING |
| FCF conversion | CFO/FCF＋corroborators | 2季負值＋1項佐證為風險；3季＋2項佐證為結構惡化 | 單季可能是WC／Capex時點 | 11筆正式／精確衍生cash-flow observations | T0/T1相容期間 | 2／3季 | Yes | FCF轉正且CFO／CCC修復2季 | Compatible cash-flow periods | PENDING |
| Working capital | Funding need ratios | ≥25%警戒；≥50% blocker候選 | 絕對資金需求必須相對可吸收資源 | Q2 AR／存貨／AP bridge；缺完整分母 | T1 bridge＋T0/T1 denominators | blocker須實際流動性佐證 | Yes | 全部比率<25%且實際流動性恢復2次 | Liquidity/net cash/CFO capacity | PENDING |
| Current balance sheet | Actual liquidity/leverage | STRONG／ADEQUATE／WATCH／STRESSED | 現況不能被假設情境降級 | Q2 actual cash/net-cash evidence | 僅T0/T1實際證據 | STRESSED復原2期 | Yes | 直接壓力解除且cash-flow支持2期 | Complete actual liquidity | PENDING |
| Stress resilience | Stress need/liquidity | ≤10%高；10–25%中；>25%低 | 衡量情境吸收能力但不等於現況 | 研究A/B為T4，非歷史結果 | T4＋T0/T1正式分母 | 每季重估 | No | 比率≤25%且實際流動性未惡化 | Same-basis liquidity | PENDING |
| Per-share compounding | Exact compounding spread | ≥3%複利；-1–3中性；-5–-1壓力；≤-5惡化 | 股數增加只有在每股價值落後時才是稀釋 | EPS/BVPS可得；期末股數歷史稀疏 | 相容T0/T1分子分母 | 強狀態2期 | No | spread≥-1連續2期 | Compatible share bases | PENDING |
| Dilution | Share growth vs per-share spreads | 2項負向spread且連續2期才為persistent risk | 不設脫離價值創造的任意股數上限 | 1筆期末股數T3、5筆WA shares T0 | T0/T1；T3僅cross-check | 2期 | No | 至少2項per-share spread非負2期 | Period-end share history | PENDING |
| Capital-light | Five factor groups | 3組同向且2期才形成強趨勢 | 避免相關原始指標重複投票 | 已修正五群組模型；Consignment占比未揭露 | T0/T1 group inputs | 2期 | No | 惡化群組少於3且cash conversion可得2期 | Complete five groups | PENDING |
| Valuation | P/E＋P/B＋P/S＋fundamentals | 至少2個倍數交叉判讀；30/70/90百分位為候選界線 | 百分位只是描述，需ROIC/FCF/per-share佐證 | PE 21、PB 21、PS 18期 | 正式price/denominators；P/S T2僅部分支持 | 正式事件後觀察 | No | 2個倍數回30–70或基本面改善 | Post-event price | PENDING |
| Core holding | Long-term corroboration | 降級須hard blocker＋2項實際不利維度＋2期 | 長期論點不可被單一弱估算推翻 | Q2獲利成長、cash conversion弱、WACC缺值 | T0/T1多維度 | 2期 | Yes | blocker解除且3項支持連續2期 | WACC/cash/current valuation | PENDING |
| Add-on gate | Seven-factor gate | 6/7支持才候選通過；3–5為PARTIAL | 同時要求創值、資金安全、每股價值與估值 | 現況缺post-event price/WACC/完整liquidity denominator | blocker與valuation須T0/T1 | 依各維度 | No | 清除blocker並恢復至少6項支持 | Current valuation/WACC/liquidity | PENDING |
| Downgrade gate | Corroborated impairment | WATCH較快；TRIGGERED須blocker＋2項實際不利因素＋2期 | WATCH與論點受損的證據強度應不同 | cash-flow反轉與ROIC/WACC缺口支持較慢trigger | T0/T1；T4不能單獨觸發 | 1／2期 | Yes | blocker解除且2項正向支持2期 | Corroboration | PENDING |
| SMART | Typed rule state | Metric、thesis、risk、policy各用自己的契約 | 可用性不等於論點或決策獲准 | Forward Model QA typed-state baseline | 繼承底層規則 | 繼承底層規則 | No | 繼承底層恢復條件 | Underlying metric inputs | PENDING |

Owner後續每列只能選擇：`APPROVE`、`MODIFY`或`REJECT`。本候選沒有自動核准或啟用路徑。
