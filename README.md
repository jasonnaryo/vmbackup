# Network Telemetry Agent

一个可部署在客户端上的轻量 Agent，用于：

1. 监听本机网络接口与网关变化。
2. 实时计算上传/下载速率。
3. 基于观测数据推测网关网络带宽（多少兆）。
4. 使用启发式规则判断网络更像“普通宽带”还是“光纤”。
5. 主动将遥测数据上报到你的服务端。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python agent.py
```

## 配置

通过环境变量配置：

- `REPORT_URL`：服务端上报地址（默认 `http://127.0.0.1:8080/telemetry`）。
- `REPORT_INTERVAL_SEC`：上报周期秒数（默认 `5`）。
- `SAMPLE_INTERVAL_SEC`：采样周期秒数（默认 `1`）。
- `HOST_ID`：客户端唯一标识（默认取主机名）。
- `AUTH_TOKEN`：可选，上报时放入 `Authorization: Bearer <token>`。

## 服务端接收 payload 示例

```json
{
  "host_id": "client-a",
  "timestamp": "2026-02-11T08:00:00.123456+00:00",
  "network": {
    "default_interface": "eth0",
    "gateway": "192.168.1.1",
    "link_speed_mbps": 1000,
    "connection_type": "fiber",
    "estimated_gateway_capacity_mbps": 500
  },
  "rates": {
    "upload_bps": 1048576.0,
    "download_bps": 3145728.0,
    "upload_mbps": 8.39,
    "download_mbps": 25.17,
    "peak_upload_mbps": 92.1,
    "peak_download_mbps": 301.2
  },
  "counters": {
    "tx_bytes": 123456789,
    "rx_bytes": 987654321
  }
}
```

## 设计说明

- 通过 `ip route show default` 获取默认网关和出口网卡。
- 通过 `/proc/net/dev` 读取各网卡累计收发字节并计算速率。
- 通过 `/sys/class/net/<iface>/speed`（若可用）获取链路速率。
- 通过历史峰值吞吐 + 链路速率做容量估计（取常见档位离散化：100/200/300/500/1000/2000/5000/10000 Mbps）。
- 网络类型判断采用启发式：
  - 链路速率 ≥ 1000 Mbps 且观测下行峰值较高 -> 倾向 `fiber`
  - 否则 -> `broadband`

> 注意：公网套餐带宽和本机瞬时流量并不完全等价，推测结果为概率性结论。

## 运行测试

```bash
pytest -q
```
