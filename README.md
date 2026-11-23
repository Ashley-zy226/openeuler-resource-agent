# 面向 openEuler 的自适应资源管控 Agent

真机联调请看 [联调说明](联调说明.md)。独立交付包可从 [GitHub Releases](../../releases/tag/v1.1-dry-run) 下载。

## 在 MacBook 上运行第一版 Agent

在项目根目录运行。需要 Python 3.10 或更高版本，使用标准库。

```sh
python3 -m agent
```

默认命令启动本地 `resourcectl` Mock，读取合成负载并输出 JSONL 决策日志。两次连续的高 CPU 负载窗口确认后，Agent 会请求 Mock 从 `default` 切到 `scx_rusty`。日志用 `sample_id` 串联采样与决策，用 `request_id` 串联切换请求、状态查询与结果。

```sh
# 仅记录决策
python3 -m agent --dry-run

# 模拟等待超时，查询执行进度，最终确认加载失败并恢复默认
python3 -m agent --scenario timeout_then_load_failed

# 保存日志
python3 -m agent > agent-replay.jsonl

# A 提供可执行文件后，在 openEuler 上用真实采样跑 dry-run
python3 -m agent --resourcectl /path/to/resourcectl
```

Mock 复用 v1.1 响应样例。每次运行创建独立的临时状态文件。采样命令用该状态填充可确认的 `active_policy`，从而在后续窗口反映切换结果。`--samples` 可传入其他 v1.1 JSONL。合成采样中的时间戳代表实验时间，`--interval-ms` 控制 Mock 播放速度。

首个 Skill 用 CPU 利用率演示分类，默认高阈值 0.70、低阈值 0.30、连续确认 2 个窗口，最短驻留 2000 ms。可用 `--cpu-high`、`--cpu-low`、`--confirm-windows`、`--min-residency-ms` 和 `--busy-policy` 调整。策略映射和阈值是演示配置，等 A 提供实测结果后再校准。调度延迟 P99 仅写入诊断日志，少于 50 个样本时记为不可用。

## 代码入口

- `agent/__main__.py` 注册 Tool 和 Skill，编排采样、决策、执行及日志。
- `agent/resourcectl.py` 封装 v1.1 CLI，处理流式采样、退出码和切换软超时。
- `agent/scheduling.py` 实现首个调度 Skill。
- `agent/mock_resourcectl.py` 提供具备切换状态的本地 CLI，供 macOS 和 Linux 回放使用。

参见[开发清单](TODO.md)和[分工与接口契约](分工与接口契约.md)。
