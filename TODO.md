# openEuler 自适应资源管控 Agent 开发清单

按阶段推进，每项标明负责人（`[A]` 执行面、`[B]` 决策与评测面、`[A+B]` 联合完成）。每完成一项请打勾，并记录日志、提交号或数据文件路径。原则：**先排雷环境、先跑通单机最小闭环，再叠加联合调控与快慢路径创新**。

详细接口定义见 [分工与接口契约](分工与接口契约.md)。

---

## 0. 契约锁定与环境排雷（第 1 天 · 风险闸门）

- [x] `[A+B]` 盘点起点：明确赛题要求、评分权重与机器分工（主实验机：A 的 5060；开发/回放：B 的 MacBook；独立复现：B 的 5060）。
- [x] `[A+B]` 锁定 v1.1 接口契约（`resourcectl sample` / `sched status` / `sched switch` / 预留 `cgroup` 子命令、错误码与 5 组标准 JSON 样例）。
- [x] `[A]` 在主实验机安装 openEuler 24.03-LTS-SP3，运行只读检查并保存输出（确认内核版本、CPU 异构拓扑、`CONFIG_SCHED_CLASS_EXT`、BTF 与 `/sys/kernel/sched_ext/state`）：

```sh
cat /etc/os-release
uname -a
lscpu -e
if [ -r /proc/config.gz ]; then
  zgrep -E 'CONFIG_(SCHED_CLASS_EXT|BPF_SYSCALL|DEBUG_INFO_BTF)=' /proc/config.gz
elif [ -r "/boot/config-$(uname -r)" ]; then
  grep -E 'CONFIG_(SCHED_CLASS_EXT|BPF_SYSCALL|DEBUG_INFO_BTF)=' "/boot/config-$(uname -r)"
fi
ls -l /sys/kernel/btf/vmlinux
cat /sys/kernel/sched_ext/state
```

- [x] `[A]` 若默认内核未开启 `CONFIG_SCHED_CLASS_EXT`，立刻确定并执行兼容方案（启用支持 `sched_ext` 的 openEuler OLK-6.6 内核配置/内核包），保留原内核启动项，并记录完整构建与安装步骤。
- [ ] `[A]` 记录主实验机噪声控制策略（电源模式、CPU governor、温控/频率监测方法、是否绑核及 P/E-core 分配说明）。

**验收**：v1.1 契约冻结；主实验机明确具备可用的 `/sys/kernel/sched_ext/state` 与 `/sys/kernel/btf/vmlinux`。

---

## 1. 手动跑通候选调度器 & 搭好框架与压测编排（第 1–2 天）

- [ ] `[A]` 固定与当前内核 ABI 兼容的 `scx` 提交号，记录工具链版本（clang/llvm/rust/libbpf/bpftool）和完整构建命令。
- [ ] `[A]` 在主实验机手动跑通 **2 个候选 `scx` 调度器**的“默认 → 候选生效 → 读取 `state`/`ops` → 卸载恢复默认”，保存真实命令与输出。
- [x] `[B]` 在 MacBook 搭建用户态 Agent 框架：实现标准化 Tool / Skill 注册机制、`resourcectl` Mock CLI，跑通合成负载的“采样 → 决策 → 切换 → 日志记录”。
- [ ] `[B]` 编写可复现压测编排脚本（`workload_runner`）：支持空闲、纯后台计算（如并行编译/CPU 压测）、前台延迟敏感（如 `schbench`）及三阶段混合场景，自动记录阶段时间标签与应用级 P99/吞吐指标。

**验收**：A 保存 2 个候选调度器的真实启停验证记录；B 能在 MacBook 上通过回放合成负载输出完整可解释决策日志，且压测脚本可交付 A 直接在真机运行。

---

## 2. 真实观测采集与候选策略实测基线（第 3–4 天）

- [ ] `[A]` 实现 `resourcectl sample`（v1.1 JSONL 输出）：先采集 `workload_features`（`cpu_util`、`iowait_pct`、`runq_len_avg`、`ctxt_per_s`）与 `cpu_psi_some_pct`、`active_policy`，再接入 eBPF 调度唤醒延迟探针输出 `sched_lat_p99_us` 与 `sched_lat_samples`（及可选 `voluntary_ctxt_ratio`）。
- [ ] `[A]` 实现 `resourcectl sched status` 与 `resourcectl sched switch`：白名单校验、串行切换、内核态生效核实、切换耗时 `elapsed_ms` 统计、只管理自身拉起的 `scx` 进程；覆盖加载失败与意外退出后自动恢复默认并回报 `recovery`。
- [ ] `[A]` 使用 B 的压测编排脚本，在相同硬件配置下分别测出默认调度器与 2 个 `scx` 候选在“纯计算 / 延迟敏感 / 混合负载”下的真实表现，保存原始采样 JSONL、应用成绩与实测策略表（默认策略也可作为某类负载的最优解）。
- [ ] `[B]` 用 A 的真实采样和异常样例替代 Mock 做回放：
  - 基于 `workload_features` 实现负载识别（避免仅凭 `sched_lat_p99_us` 引发自激振荡）。
  - 对接实测策略表，加入**连续窗口确认、最短驻留时间、切换后观察期、小样本 P99 保护（`sched_lat_samples` 阈值）**。
  - 实现 CLI 超时先查 `sched status`、以及连续性能退化触发回退逻辑。

**验收**：同一份真实采样日志在 B 端可 100% 复现同一决策；无短暂抖动误切换、无切换后自激振荡；策略表中至少存在相对默认调度器有明确正收益的场景。

---

## 3. 首次真机联调闭环（第 5 天）

- [ ] `[A+B]` 在主实验机接入真实 `resourcectl`，先开启 `dry-run` 模式（只观测和记录决策、不执行切换），核对识别结果与压测阶段标签。
- [ ] `[A+B]` 开启自动切换，运行三阶段场景（纯后台计算 → 叠加前台延迟敏感 → 停止前台任务），输出统一时间线日志。
- [ ] `[A+B]` 注入故障测试：未知策略、加载失败、运行中强杀 `scx` 进程、Agent 正常退出，确认系统安全恢复默认调度且日志完整。

**验收**：同一份时间线清晰核对 5 件事——①负载何时变化、②Agent 何时识别、③何时请求切换、④内核实际生效了什么及耗时多少、⑤切换前后前台 P99 与后台吞吐的真实变化。

---

## 4. 正式基线性能对比（第 2 周）

- [ ] `[A]` 固化一键实验脚本，在相同硬件状态与负载参数下运行 4 组对照：**默认调度 vs 固定候选 A vs 固定候选 B vs 基础自适应 Agent**（覆盖单负载与阶段变化混合负载）。
- [ ] `[A]` 严格区分调参数据与评测数据：每组至少独立运行 5 次并交错顺序，保存逐轮原始数据、CPU 频率/温度与切换日志。
- [ ] `[B]` 编写自动化统计与画图脚本，由原始数据一键重建结果表：
  - 延迟/耗时改善率 = `(默认值 − Agent 值) / 默认值`；吞吐改善率 = `(Agent 值 − 默认值) / 默认值`（均报告中位数、波动范围、百分比与原始单位）。
  - 单独统计 Agent 开销（CPU 占用、内存占用、切换次数与切换耗时），并如实标出退化场景与原因。

**验收**：评审运行脚本即可从原始数据重建全部对比图表，清楚回答哪些负载受益、收益多大、代价是多少。

---

## 5. 核心创新与 eBPF 扩展落地（第 2–3 周）

- [ ] `[A]` 实现 eBPF + cgroup 扩展后端：使用 eBPF hook 采集专用测试 cgroup 的运行/限流事件，提供 `resourcectl cgroup status/set/reset`（受控调整并恢复 `cpu.weight` / `cpu.max`）。
- [ ] `[B]` 将 cgroup 能力注册为独立 Tool / Skill，验证可独立启停并完整记录 hook 事件、决策、权重变化与恢复结果。
- [ ] `[A+B]` 实现**联合调控 Skill（`scx` + `cgroup` 协同）**：在混合负载下以“压低前台 P99 + 守住后台吞吐下限”为目标，与“单切 `scx`”和“默认调度”做独立对照实验。
- [ ] `[B]` 实现**快慢双路径 Agent**：快路径负责低开销秒级控制；慢路径接入 LLM 用于高层 SLA 意图解析、未知负载/退化归因、策略参数或权重建议，记录慢路径对决策质量、响应延迟与资源开销的消融对比。

**验收**：eBPF 扩展无缝融入统一 Tool/Skill 框架，且有明确对照数据证明创新机制相对基线 Agent 的增量价值。

---

## 6. 监控展示、独立复现与答辩交付（第 3–4 周）

- [ ] `[B]` 开发实时/回放监控界面，同屏展示负载特征、Agent 决策与理由、实际生效策略与 cgroup 状态、前台 P99 与后台吞吐对比。
- [ ] `[A+B]` 整理完整 README（内核配置、scx 提交号、依赖、权限、一键构建/运行/实验/清理命令）。
- [ ] `[A+B]` 在干净的 openEuler 24.03-LTS-SP3 环境（B 的 5060 笔记本）严格按 README 独立复现一次，单独记录第二台机器结果。
- [ ] `[A+B]` 排练现场演示：展示目标环境 → 启动阶段变化负载 → 观察自动切换与联合调控 → 展示实时性能改善 → 停止并确认恢复默认。

**验收**：代码、文档、原始数据、复现脚本与演示全套闭环，准确对齐“创新性 30 / 功能 25 / 性能 25 / 代码 10 / 演示 10”五项评分标准。

---

## 参考入口

- [任务说明](任务说明.md)
- [分工与接口契约](分工与接口契约.md)
- [openEuler 官方镜像目录](https://repo.openeuler.org/openEuler-24.03-LTS-SP3/)
- [Linux sched_ext 文档](https://docs.kernel.org/scheduler/sched-ext.html)
- [scx 上游仓库](https://github.com/sched-ext/scx)
- [SchedCP 实现](https://github.com/eunomia-bpf/schedcp)
- [LAPS 实现](https://github.com/lvmiao233/LAPS)
