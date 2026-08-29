# Enterprise Value Owner Policy Revision V1

本文件只呈現 Owner 要求修改的八項政策設計。原候選的五項 `APPROVED_DESIGN` 以 semantic SHA 凍結，未在本文件重新校準。所有八項仍為 `REVISION_PENDING_OWNER_REVIEW`；政策未啟用、不可發布、`actionable=false`。

| Policy Dimension | V1 Candidate | Owner Concern | V1 Revised Proposal | Behavioral Difference | Remaining Input Dependency | Owner Decision |
|---|---|---|---|---|---|---|
| FCF Conversion | 以連續負值季數主導結構性升級 | 鴻海現金流具季節性與營運資金波動 | 優先同季、TTM、FY；結構性狀態須現金轉化、CFO與獨立佐證共同成立 | 三個單季負 FCF 不足以判定結構惡化；一個好季度也不能解除 | 同季／TTM／FY、CFO、CCC、營運資金、ROIC、Capex 回報 | PENDING_REVIEW |
| Working Capital / Funding | 25% WATCH、50% hard-blocker 候選 | 分母順位未治理，負 CFO 可能產生誤導比率 | 分母依流動性、淨現金、正規化正 CFO 排序；25%／50%僅研究帶 | 缺有效分母、Owner 門檻及實際證據時不得啟動 blocker | 同基準流動性、淨現金、正 CFO 與 Owner 數值校準 | PENDING_REVIEW |
| Per-share Compounding | 多項每股指標共用區間，含單季 FCF/share | 單季 FCF/share 季節性太高 | EPS、BVPS、FCF/share 各用相容期間，保留精確複利公式 | 至少兩項相容正向指標且持續兩期；單季 FCF/share 僅佐證 | 相容股數、分子期間與長期間 FCF/share | PENDING_REVIEW |
| Capital-Light | 三個同向群組可定方向 | 強狀態缺完整性閘門 | 五群組至少四個可評估、三個同向、持續兩期 | 少於四群組僅 PARTIAL／INCONCLUSIVE；不對 Consignment 作因果斷言 | 五個群組的可比觀察 | PENDING_REVIEW |
| Valuation | 30／70／90 分位映射估值狀態 | 易被誤認為內在價值、交易或安全邊際門檻 | 分位僅描述歷史位置；至少兩倍數並結合 ROIC／ROE／FCF／每股價值 | 安全邊際待 Owner 數值校準；當期判斷須 POST_EVENT／REPORT_CUTOFF | 當期價格、兩項倍數、Owner 安全邊際校準 | PENDING_REVIEW |
| Core Holding Thesis | 漸進降級以 hard blocker＋兩維度兩期為主 | 真正論點失效事件可能需更快 REVIEW | Path A 為強、直接、重大 T0/T1 事件；Path B 為多因子持續惡化 | REVIEW 可加快；T2 單獨不得降級 | 直接事件或多期實際基本面佐證 | PENDING_REVIEW |
| Add-on Capital Gate | 七因子等權，6/7 支持 | 經濟權重不同，次要信心不得蓋過核心閘門 | mandatory gates＋四項核心支持＋secondary confidence | 移除 6/7；mandatory 失敗不得 PASS；PARTIAL 非交易指令 | 當期估值與 ROIC／FCF／Funding／每股價值狀態 | PENDING_REVIEW |
| Thesis Downgrade Gate | 未確認 T4 concern 可進 WATCH | 情境關注不等於不利證據 | T4 只產生 scenario flag；WATCH 要 actual/direct 或 T2＋獨立佐證 | T4 單獨不得 WATCH／TRIGGERED；解除須多次確認 | 有意義實際證據、T2 佐證與多期確認 | PENDING_REVIEW |

未解依賴：governed WACC、當期價格、同基準流動性／淨現金、正規化 CFO、相容股數與長期 FCF/share、Owner 安全邊際及 funding 數值門檻。此 revision 不取得或推算任何缺失資料。
