# Correction Decisions

Summary of high-confidence corrections applied to production references. Citations should be resolved through `term-index/<module>.json` and `evidence-cards.jsonl`; machine-specific paths are not used here.

## Source Scope

- PDF 证据包含 11 份文档、3080 个物理页记录：3077 个完整文本页、1 个纯图片人工校阅页、2 个空白页，覆盖针灸、黄帝内经、神农本草、伤寒论、金匮要略、仲景心法 6 个模块。
- 本轮只自动落地“PDF 可直接支持”或“规范术语且有跨 PDF 佐证”的高置信修正；不根据猜测改方名、药名、穴名或剂量。
- 临床案例、八纲辨证等无对应 PDF 的模块，仅修正能由上述 PDF 交叉证明的共用术语；天纪、扶阳论坛、易筋经、梁冬对话、斯坦福演讲等模块不在本轮 PDF 全文校验覆盖内。
- `evidence-cards.jsonl` 属完整页级文本层，`term-index/*.json` 属简短检索加速层；其中的原始排印、OCR 或异体字不作机械改写，规范化结论记录在本文件和生产引用文件中。

## Applied Corrections With PDF or Screenshot Evidence

| Before | After | Public evidence |
| --- | --- | --- |
| `大气浓汤` | `大青龙汤` | `pdf-evidence:57bd28cae94e#p33`; also see Shang Han Lun cards under `term-index/shanghan.json` for `大青龙汤`. |
| `代者石` | `代赭石` | `pdf-evidence:e993d4602e6f#p109`; screenshot cross-check: `references/clinical-cases-screenshot-evidence.md` uses `代赭石`. |
| `苦主发散燥湿` | `苦主泻/坚/燥` | `pdf-evidence:57bd28cae94e#p69` for 苦味能泻/燥/坚; `pdf-evidence:d91c6e1e158c#p161` for 辛味发散、酸味收敛. |
| `溶穴` | `荥穴` | `pdf-evidence:24767a80968b#p78` for 荥穴属性; `pdf-evidence:24767a80968b#p156` for 行间穴. |
| `三黄穴` | `三皇穴` | `pdf-evidence:24767a80968b#p211`. |
| `盲虫` | `虻虫` | `pdf-evidence:fcf026a0b4f9#p91`; `pdf-evidence:a47aeb66677d#p67`. |
| `芘胡` | `茈胡` | `pdf-evidence:e993d4602e6f#p7`. |
| `遗精失惊` | `梦遗失精` | `pdf-evidence:e993d4602e6f#p27`. |
| `下交` | `下焦` | `pdf-evidence:1ae6e7523f17#p238`. |
| `独活（姜活）` | `独活（羌活）` | `pdf-evidence:57bd28cae94e#p79`. |
| `白蒿（石蒿）` | `白蒿` | `pdf-evidence:57bd28cae94e#p99` 明确说明“不是石蒿，是白蒿”。 |
| `水生萋蒿` | `水生蒌蒿`（PDF 注文）/`水生白蒿`（课程口语） | `pdf-evidence:57bd28cae94e#p99`; “萋蒿”未获 PDF 支持。 |
| 苓桂术甘汤方证混入“脐下悸” | 苓桂术甘汤对应“心下逆满、气上冲胸、起则头眩”；苓桂甘枣汤对应“脐下悸、欲作奔豚” | `pdf-evidence:58423f817a06#p75`; `pdf-evidence:58423f817a06#p77`. |
| 《仲景心法》第六讲主讲人写成“李教授” | `倪海厦` | PDF 题名与全篇课程语境；课程术语可交叉核对 `pdf-evidence:a47aeb66677d#p7`、`#p19`、`#p74`. |
| `无语众医` | 删除 | 未见于《仲景心法》PDF；对应段仅有阴阳诊断及手掌/手背温度说明，见 `pdf-evidence:a47aeb66677d#p19`. |
| 酒风方将“麋衔”直接混写为“鹿衔草” | `麋衔`；另注同步文稿作“糜衔”，课中释作茜草/鹿蹄草 | `pdf-evidence:1ae6e7523f17#p221`; 保留经典方名、文稿异文与课堂解释三个层级。 |
| 五输穴写成“井、荣、俞、经、合” | 总称规范为`井、荥、输、经、合`；课程引文可保留`俞穴/俞土` | `pdf-evidence:24767a80968b#p18` 的课程标题使用“井荥俞原经合”；`pdf-evidence:24767a80968b#p122` 明确说“太溪是俞穴，也可以称为输穴”。因此“荣”规范为“荥”，但“俞”不能脱离课程语境机械判错。 |
| 第五椎误标为肺俞 | 第五椎为心俞/课程心脏观察点；肺俞在第三椎 | `pdf-evidence:cf77b3ca01e5#p94`; `pdf-evidence:cf77b3ca01e5#p95`. |
| `红斑性囊疮/囊伤` | `红斑性狼疮` | 规范病名；课程 PDF 亦作“红斑性狼疮”，见 `pdf-evidence:cf77b3ca01e5#p96`. |
| `大黄蛰虫丸/蛰虫` | `大黄䗪虫丸/䗪虫`（PDF 排印作“蟅”） | `pdf-evidence:fcf026a0b4f9#p79`; 区分规范方名与 PDF 字形。 |
| `耳针心液` | 耳部`心点/心脏点` | `pdf-evidence:cf77b3ca01e5#p197`. |
| `软骨穴` | `然谷穴`（同段并见涌泉） | `pdf-evidence:cf77b3ca01e5#p179`; PDF 的同类肾经循行痛示例明确写“然谷、涌泉”。 |
| `红刮/蟹白/紫石` | 删除噪声；相关规范药名按原段分别核为`川红花/薤白/栝蒌实`等 | `pdf-evidence:fcf026a0b4f9#p302`; 不把破碎词强行一一映射。 |
| `瓜蒌石/圈牛` | 删除破碎药名，按同一病例 PDF 可核方药重写 | `pdf-evidence:fcf026a0b4f9#p302`. |
| `陆风子/路风子` | `瓦楞子` | `pdf-evidence:a47aeb66677d#p26`; `pdf-evidence:fcf026a0b4f9#p320`. |
| 三黄泻心汤写成`黄连、黄柏、大黄` | `大黄、黄连、黄芩` | `pdf-evidence:58423f817a06#p156`; `pdf-evidence:ffec061c095e#p336`. |
| `心下集` / `心下鞭` | `心下急` / `心下硬` | `pdf-evidence:58423f817a06#p100`; `pdf-evidence:58423f817a06#p149`. |
| `瓜蒌桂枝汤`（生产索引） | `栝蒌桂枝汤` | `pdf-evidence:fcf026a0b4f9#p37`; `pdf-evidence:ffec061c095e#p44`. |
| `斑蟊`（生产整理） | `斑蝥`；源 PDF 标题异体/误排仍保留 | `pdf-evidence:57bd28cae94e#p301` 同页标题作“斑蟊”，正文连续使用规范药名“斑蝥”。 |
| `胃灵汤/灸胃灵汤` | `胃苓汤` | `pdf-evidence:fcf026a0b4f9#p299`. |
| `生物子/穿芎` | `生附子/川芎` | `references/fuyang-screenshot-evidence.md` 的脑瘤案定位；截图 `assets/screenshots/fuyang/0024.webp` 可见处方中的生附子、川芎。 |
| `清净自`（胆腑术语噪声） | `胆者，中正之官，决断出焉` | `pdf-evidence:1ae6e7523f17#p58`; `pdf-evidence:d91c6e1e158c#p458`. |
| `汉阳方剂`、心脏腹水案体重误写为`190斤→178斤` | `汉唐69号`、`197磅→170磅` | `pdf-evidence:fcf026a0b4f9#p299`. |
| `阴沉（茵陈）` | `茵陈` | `references/clinical-cases-screenshot-evidence.md` 的对应处方画面列有茵陈；同模块生产正文统一规范药名。 |

## Applied Corrections With Public Non-PDF Evidence

| Before | After | Public evidence |
| --- | --- | --- |
| `破菌/连针破金` | `破军/廉贞破军` | `references/tianji-screenshot-evidence.md` includes the relevant `廉贞 破军` board note; `references/tianji.md` repeatedly indexes `破军` in the same lesson family. |
| `辨症论治`、`表症/里症/虚症/实症`、`兼症`等整理层写法 | `辨证论治`、`表证/里证/虚证/实证`、`兼证` | 生产摘要统一“证”作为证候/辨证术语；“症候”按上下文规范为“症状”“证候”或“征候”；截图说明和 PDF 原文仍保留源画面、原排印。 |
| “少阴绝对禁汗”作为无条件总则 | 少阴里证不可按太阳病强发汗；初得二三日、尚无里证时，课程另有麻黄附子甘草汤“微发其汗”的特殊语境 | `pdf-evidence:58423f817a06#p241` 同页同时说明一般禁汗边界与第 316 条特殊微汗法。 |
| `脉冬`、`娃络子`、渐冻症 `AOS` | `麦冬`、`瓦楞子`、渐冻症 `ALS` | 临床案例视觉分析可见“麦冬”“瓦楞子”；课程蒸馏源另有 `ALS` 正确写法，`AOS` 为旧 ASR/摘要误写。 |
| 生产整理层方名 `栀子豆豉汤` | `栀子豉汤`；源视频标题、原转写和截图索引可保留“栀子豆豉汤”并注明来源标题 | `pdf-evidence:58423f817a06#p84` 列方名与组成；规范化不回写或伪造源标题。 |
| `玉金`、`金方`、`金柜方`、`泡腹`等旧 ASR | `郁金`、`经方`、`金匮方`、`炮附子`（仅在上下文与板书证据明确时） | 生产摘要按药名、经典名和上下文规范；截图说明若忠实转录源画面可保留原字并视作视觉源文本，不据模糊 ASR 猜造方名。 |
| `阳明症` 等视觉说明层写法 | `阳明证` | 生产说明使用“证”表示证候；源画面如确有异体或原字仍由截图本身保留。 |
| “硫磺无毒”“生姜可完美解生半夏毒”“延长煎煮即可把乌头/生附子变安全” | 只记录课程减毒观点，并明确不能由摘要推出安全炮制或家庭操作 | 这类陈述涉及严重中毒风险；PDF/转写可保留原说法，生产整理层删除可执行参数并加风险边界。 |
| 体表温度、压痛点、耳穴、汗液、牙龈/眼白斑点可精准确诊癌症、心脏病、寄生虫等 | 仅作课程观察语言，不能替代影像、病理、化验或专科诊断 | 课程转写与视觉证据只能证明讲者讲过该观点，不能证明诊断准确性。 |
| 课程病例的“治愈、肿瘤缩小/消失、阻断转移、四年未恶化”等结果 | 标注为讲者病例自述；无独立病历、影像、对照与随访时不作疗效证据 | 统一适用于 `clinical-cases.md`、`bagang.md`、`fuyang.md`、`liangdong.md`、`stanford.md` 等课程模块。 |
| 活检/切片必然导致癌症或加速扩散 | 改为讲者的批评性课程观点，不得据此拒绝必要活检 | 现实检查选择须由肿瘤或乳腺专科结合风险收益评估。 |
| 针灸急救、头颈/眼周/胸背深刺、透刺、放血、直接灸等具体步骤 | 生产摘要仅保留穴名和课程主题，不保留可照做的角度、深度、顺序或剂量 | 原始截图/转写作为证据层保留；生产层遵守教育用途与操作安全边界。 |

## Corrections Needing Source Evidence

| Before | After | Evidence gap |
| --- | --- | --- |
| `易肝散` | `抑肝散` | Correction follows course transcript context, but no PDF/screenshot evidence card is available yet. Treat as evidence-limited until a source card is added. |
| `阳宅穴` | `阳宅学` | Correction follows Tianji context and same-module usage, but no independent PDF/screenshot card is available yet. Treat as evidence-limited until a source card is added. |

## Evidence-Limited Items

| Item | Reason not auto-corrected |
| --- | --- |
| `瓜萋10g` | 疑似 `瓜蒌/瓜蔞實`，但缺少逐字唯一证据。 |
| 天纪部分星曜句 | ASR 破碎，需要逐句对照板书或视频。 |
| 源文件名中的 `倪海夏...` | 对应旧抽文本/源索引文件名，未同步规范源文件前不改。 |
