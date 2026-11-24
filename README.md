# 青汀薄膜测厚采集台

青汀薄膜小试室的班长导入试涂计划，采集员办理双探头工单和撤单原据，质检员签存测厚值、核对班表并按成果号追查出处。两路各有独立的接受顺位及实采序位。同路可复用读码，设备实际采样、原样到达与结清单到达各自推进。

需要 Python 3.11 和标准库。请从项目根目录运行，控制台物化项目时提供标准回归入口。

```sh
python3 -B check_project.py
python3 -B -m station.work.runtime demo samples/reopen.json
```

演示从临时空站库回放。早班按 R、A、B 登记，右路规程为每计数 1/3 μm，左路为 1/2 μm。A 采到 14 计数后撤单，原样迟到并留作 7 μm 撤单原据。B 的 22 计数签为 11 μm，右路 R 的 21 计数签为 7 μm，班表顺序 R、B，均值 9 μm。演示包含待查重开、提交失败后续签、停源复领和真实出处。另有普通双路、撤单后已采迟到、撤单后实际未采的录制。

## 站台接口

`from station.work.runtime import open_station`。`open_station(path)` 可作上下文管理器，路径指向操作者的 SQLite 文件。`station.reopen()` 关闭并重新装配同一路径；设备开关、规程和已提交状态保持。开班只由显式导入触发。标识为非空字符串，票号在一个站库内唯一，路别是 `left` 或 `right`，顺位和实采序位是正的 SQLite 整数，原值为整数，出处为非空字符串。

| 调用 | 业务语义 |
| --- | --- |
| `open_shift(shift_id, ruleset, tickets)` | `ruleset` 形如 `{'version': 'V1', 'factors': {'left': [1, 2], 'right': [1, 3]}}`。有序票清单的每项含 `ticket_id`、`lane`、`code`。两路分母均须非零。参数含原票序和原系数分量。原参返回当前登记事实，异参或无效票原子拒绝。`read_shift_setup(shift_id)` 可查询配置与票状态。 |
| `dispatch_ticket(ticket_id, request_id)` | 返回 `DispatchStatus`，状态为 `waiting` 或 `accepted`；后者含 `DispatchLink`。同票最多接受一次，已接受的有效票请求可在设备不可用时回放，已撤票拒绝派发。`dispatch_status(ticket_id)` 查询持久状态，未派发返回 `None`。 |
| `cancel_ticket(ticket_id)` | 返回票及当前设备结局。撤单终止领件资格，定稿票保持原交付。`read_cancellation_evidence(ticket_id)` 区分 `not_dispatched`、`awaiting_settlement`、`unsampled`、`awaiting_sample`、`received`，收到已核撤单原样后附原样和换算结果。 |
| `accept_sample(sample)` | 接纳 `RawSample(lane, code, sequence, raw_value, source)`，返回首收、是否重投及可选确切归属。`read_arrival(lane, sequence)` 查询首收与当前归属。 |
| `settle_lane(cut)` | 接纳 `LaneSettlement(lane, through, items)`，截点 `through` 覆盖本路第 1 至该顺位的全部接受项，0 是空截点。`SettlementItem(acceptance_id, sequence)` 中 `None` 表示确定未采。返回已核逐项终局；重复或较小截点可以重投，冲突整单拒绝。在线设备生成的单可在随后导入。 |
| `issue_ticket(ticket_id, request_id)` | 确切原据齐备才签存，返回固定成果和 `first_receipt`。同请求异票拒绝。已签票回放原成果和首执。`read_ticket_evidence(ticket_id)` 可在签存之前核对原据。 |
| `read_shift(shift_id)` | 返回 `ShiftSheet`，包含按原票序排列的成果、`count` 和 `mean_micrometers`。空班均值为 `None`，未知班次拒绝。 |
| `read_result(result_id)` | 停源后仍可按号查询固定成果。`read_receipt(receipt_id)` 查询首执。两者对缺失记录均返回 `None`。 |

业务拒绝使用 `StationError`，其 `code` 可用于区分原因。原据尚在等待时签存报 `evidence_pending`，已结清未采报 `unsampled`，撤单票报 `withdrawn`。`fail_next_issue()` 可安排一次提交前失败，测试时可在提交失败后查询原据、班表、成果和首执，再用原请求续办。站台事务覆盖设备接受与派发关联、结清与归属、成果与首执三个写入边界。等待设备或原样期间可继续操作另一路。

## 设备与录制

`station.device.set_online(enabled)` 和 `set_lane_ready(lane, ready)` 持久设置在线及本路接单状态。`sample(acceptance_id, raw_value, source, sequence=None)` 为一条接受单执行一次采样；省略序位时取本路下一个序位，显式序位须严格递增。`deliver(lane, sequence)` 可反复读出已实采的原样，`settle(lane, through=None)` 在线冻结覆盖项，省略截点则覆盖该路当前全部接受。暂停一路接单期间，已接受的工单仍可采样及结清。停源后站务已保存的结清、原样和成果可继续核对。

`load_recording(path)` 读取 JSON，`station.play_recording(recording)` 按顺序通过正常接口执行各具名步骤并返回逐步实测状态。录制定义班次、规程、票及形如 `[步骤名, 操作名, 参数…]` 的事件，示例见 `samples/`。序位、出处、重开及停源时点均由录制设定。微米值和均值在 Python 接口中是约分后的 `Fraction`，演示 JSON 用精确分数字符串呈现。
