# Treasury Calendar

美国财政部国债拍卖、季度再融资公告（QRA）及融资预估独立日历。无 API Key，不连接券商、不下单。

## 安装
1. 创建公开仓库 `treasury-calendar`，上传 `treasury_calendar.py`、`test_treasury_calendar.py`、`requirements.txt`、`dates.json`、`treasury.ics`、`README.md`。
2. 单独创建 `.github/workflows/update-calendar.yml` 并复制工作流。Actions → Update Treasury Calendar → Run workflow。
3. 确认成功后订阅 `https://raw.githubusercontent.com/你的用户名/treasury-calendar/refs/heads/main/treasury.ics#1`。
4. 新日历显示后，在 economic-calendar 的 config.json 将 `treasury_auction` 改为 `false`，保留其余配置。

## 数据和限制
- 财政部官方 tentative auction schedule PDF 给出未来日期；Fiscal Data auctions_query 提供正式记录和 competitive close time（如果已经提供）。未确认的时刻用全天 Time TBD，不用统一的 13:00。初始快照含 2026 年 11 月 16 日至年底的拍卖及两组季度公告；4 个近期拍卖时刻来自已公布数据的公开报道，仍需核对正式公告。
- QRA 网页给出当前与下一季度日期及常规发布时间。下一次发布时间按同类别官方网页时间处理，变更须核对。日历保留部分历史拍卖；未来日期会按最新官方排期替换。
- 每小时 UTC 第47分钟检查，GitHub/Google 可能延迟。任一必需来源失败、解析异常或排期过期则不发布，旧日历保留。正式数据 API 是否及时覆盖未来拍卖取决于官方数据发布；尚未收录的临时现金管理券可能缺失。不包括财政部回购、结算日提醒、拍卖结果具体发布时刻或 TGA 余额。
- 15 分钟事件长度仅为提醒；所有定时事件自动按纽约时区转 UTC。不要将日历作为自动交易或精确下单触发依据。

## 本地测试
`pip install -r requirements.txt`；`python -m unittest -v`；`python treasury_calendar.py --offline`。联网更新还需 `pdftotext` (macOS: `brew install poppler`)。网络端到端待 GitHub Actions 验证。

官方来源：https://www.treasurydirect.gov/auctions/auction-announcements/ 、https://home.treasury.gov/system/files/221/Tentative-Auction-Schedule.pdf 、https://home.treasury.gov/policy-issues/financing-the-government/quarterly-refunding/most-recent-quarterly-refunding-documents 、https://fiscaldata.treasury.gov/datasets/treasury-securities-auctions-data/ 。
