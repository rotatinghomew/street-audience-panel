# street-audience-panel

街头巡演的现场轮次、名册覆盖和节期补访交接。 其中人物代号、机构、交易及历史回执均为合成资料。

## 数据约定

`data/layout.json` 逐一解释业务表及 CSV 列顺序，`data/rules.json` 记录运营口径。CSV 使用 UTF-8、首行为列名；空白字段表示未提供或不适用，`+` 隔开多值字段。历史记录的业务时刻与送交时刻含义不同，按各表说明解释。

- `performances.csv`：同一节期节目和停靠点，线路可交叠。
- `frame.csv`：家庭抽样层；covered 是名册覆盖人口，eligible 是本期经社区确认的常住人口数。
- `rounds.csv`：现场的轮次设计、抽中的入口及系统抽取步长。
- `audits.csv`：现场访问的一次进入；同一队伍可以再次进场。unit_hint 严格分配给现场访问表单，不是全局人号。
- `residents.csv`：社区访问个体、家庭与自报观看；多场用 + 拼接，未答不同于未看。
- `links.csv`：同组候选可受联合条件限制；same / different 是现场确认，possible 为尚待确认。
- `follow_up.csv`：班次可询问的一组事件；accepted 先占本日额度，单份访问需一次额度。
- `roster.csv`：后续名册覆盖的独立登记及保存截面，known=unknown 只说明未访问。
- `plans.csv`：封存名册公开的抽取机会及所占班次；原层 S4 名册此时才可用于以后访问，不回填旧覆盖。
- `returns.csv`：同一 contact 有两种用途时仍分别形成实际回执。phase=verify 不属于抽样。
- `availability.csv`：实际班次与已发出的随机邀请回执。无法成行不自动注销接受者已有回访安排。
- `releases.csv`：文化馆实际发出的估计适用范围；记录截面并非新的补访口径。

## 本地检查

使用 Python 3.11 及标准库。`python3 inspect_inputs.py` 读取原始资料并列出记录数；`python3 -m unittest discover -s tests` 检查输入资料。检查不计算或发布业务结论。
