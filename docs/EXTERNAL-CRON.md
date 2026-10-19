# 外部定时兜底（cron-job.org）

三个时段（北京 04:00 / 12:00 / 20:00）由三层保护：

| 层 | 位置 | 作用 |
|---|---|---|
| 1 | `daily.yml` 的 `Publish` 步骤 | 失败自动重试 3 次（30s / 60s 间隔） |
| 2 | `watchdog.yml` | 时段后 70 分钟检查，没日报且上次失败则重跑 |
| 3 | `slot-kick.yml` + 外部 cron | GitHub 调度被丢弃时，由外部服务补一次 |

本文档只讲第 3 层怎么接。

---

## 为什么需要它

GitHub 的 `schedule` 是尽力而为：官方文档写明高负载时会延迟，**排队任务可能被丢弃**。
本仓库实测：最近 20 次定时触发里，10 次发布成功，**3 次连 job 都没创建**。

第 1、2 层都在 GitHub 内部运行，无法弥补「触发器根本没到」的情况。

---

## 接线步骤

### 1. 创建 fine-grained token

GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token

```
Repository access : Only select repositories → siweimidu/ai-ribao
Permissions        : Repository permissions → Contents: Read-only  ← 只需要这一项
Expiration         : 90 天（到期需更换；建议同时设个日历提醒）
```

> 只需要 `Contents: Read-only`。`repository_dispatch` 走的是 Contents 权限，
> 不需要 `Actions: write` —— 这正是选 `slot-kick.yml` 而不是直接调 `daily.yml` 的原因。

### 2. 在 cron-job.org 建三个任务

注册 https://cron-job.org （免费，无需信用卡），新建 3 个 cronjob：

| # | 标题 | 执行时间（北京时间） | cron 表达式 |
|---|---|---|---|
| 1 | AI日报-早 | 04:20 | `20 4 * * *` |
| 2 | AI日报-中 | 12:20 | `20 12 * * *` |
| 3 | AI日报-晚 | 20:20 | `20 20 * * *` |

每个任务的**共同配置**：

```
URL          : https://api.github.com/repos/siweimidu/ai-ribao/dispatches
Method       : POST
Timezone     : Asia/Shanghai
Schedule     : 见上表
```

**Headers**（4 条，缺一不可）：

```
Authorization  : Bearer ghp_xxxxxxxxxxxxxxxxxxxx      ← 第 1 步的 token
Accept         : application/vnd.github+json
Content-Type   : application/json
User-Agent     : ai-ribao-cron                          ← GitHub 要求必须带 UA
```

**Request body**：

```json
{"event_type": "slot-kick"}
```

**Advanced** 里建议打开：

- Follow redirects：开
- Treat 2xx as success：开
- 失败通知邮件：开（这样外部服务也会在失败时通知你）

### 3. 验证

建好后在 cron-job.org 点每个任务的 **TEST RUN**，然后：

```powershell
gh run list --repo siweimidu/ai-ribao --workflow=slot-kick.yml --limit 3
```

应当看到 `Slot kick` 运行成功。点开日志确认：

```
# 已有日报时
in_flight=0
{"date": "...", "publish": false, "reason": "...已发布..."}
##[notice]this slot has already been delivered -- nothing to do

# 需要发布时
in_flight=0
{"date": "...", "publish": true, "reason": "..."}
##[notice]dispatched daily.yml
```

---

## 幂等性：反复触发也只发一次

`slot-kick` 有两道判断，任一命中就跳过派发：

1. **已有运行在进行**（`in_progress` / `queued` / `pending`）→ 跳过；
2. **gate 说这个时段不用发**（退出码 10 已发布、11 太早）→ 跳过。

实测：连续触发两次，两次都输出 `in_flight=2` 与 `this kick is redundant`，
没有产生任何 `daily.yml` 运行。

所以外部服务可以设得比时段更频繁（例如每小时一次），
真正需要发布的时段才会派发，其余全部空转，成本只有一个 5 分钟的轻量 job。

---

## 这个 token 泄露了会怎样

`Contents: Read-only` 且只对一个仓库有效：

- 能读代码（本来就是公开仓库）；
- 能触发 `repository_dispatch`，也就是让 `slot-kick.yml` 跑一次；
- **不能**读取 secrets、不能改代码、不能删仓库、不能直接触发 `daily.yml`。

最坏情况是被人反复触发 `slot-kick`，而它对每次触发都只会：跑一次 gate、多半判定无需发布、
结束。刷不出内容，也花不掉配额（单次 job 约 40 秒）。

即便如此，token 到期就换，泄露了就立刻 revoke。

---

## 回退

不想用外部服务时，删掉 cron-job.org 上的三个任务即可。
`slot-kick.yml` 留着无害——它只被 `repository_dispatch` 和手动触发，不会自己跑。

前两层（重试 + watchdog）不受影响，仍然工作。
