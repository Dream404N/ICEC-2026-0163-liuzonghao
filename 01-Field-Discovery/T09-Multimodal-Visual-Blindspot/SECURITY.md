# 课题 09 · 密钥与数据脱敏说明

## 结论

**仓库里没有任何 API key、token、密码或账单凭证。** 硅基流动的密钥只存在于本机仓库之外的文件里，
工具在运行时临时读取，只用于给 `api.siliconflow.cn` 的 HTTPS 请求加 `Authorization` 头。

## 密钥在哪里、怎么读

`tools/vlm_bench.py::load_key()` 按以下顺序取密钥：

1. 环境变量 `SILICONFLOW_API_KEY`（名字可在 `config.example.json` 的 `api_key_env` 改）；
2. 环境变量没有时，读 `key_file` 指向的文件。默认值 `../../../../.workbuddy/.siliconflow_key`
   是相对 `tools/` 目录解析的，指向**工作区根目录的 `.workbuddy/`**，不在本仓库目录树内。

本机实际保存位置：

```
C:\Users\Administrator\WorkBuddy\2026-11-07-20-22-12\.workbuddy\.siliconflow_key
                                              ↑ 仓库（ICEC-2026-0163-liuzonghao）之外
```

密钥没有写进任何源码、配置模板、报告、CSV、JSONL、提交信息或 commit body。

## 提交前的机械拦截

仓库根 `.gitignore` 已加入：

```gitignore
*.key
.env
.env.*
config.json
*api_key*
**/data/thumbs/
```

含义：

- `*.key` / `.env*` / `*api_key*` 兜底拦住任何误命名的密钥文件；
- `config.json` 是本地覆盖配置（可能含自定义 `key_file` 路径），只在本机存在，不入库；
- `**/data/thumbs/` 是 1280px 中间缩略图，属于可再生的缓存，不占仓库体积；
- 同步脚本 `.workbuddy/sync_to_github.py` 只提交有差异的受控文件，且在提交前后都做本地/远端一致性镜像。

每次提交前可用下面两条命令自查（不输出密钥本体，只报命中文件）：

```bash
# 1) 全仓扫描是否出现 sk- 开头的密钥串（应无输出）
python -c "import pathlib,re,sys; p=pathlib.Path('.'); hits=[str(f) for f in p.rglob('*') if f.is_file() and '.git' not in f.parts and re.search(rb'sk-[A-Za-z0-9]{16,}', f.read_bytes()[:2_000_000])]; print('HIT:',hits) if hits else print('CLEAN: no API key in repo')"

# 2) 确认密钥文件确实在仓库外且被忽略
git check-ignore -v ../../.workbuddy/.siliconflow_key 2>/dev/null || echo "该文件不在仓库树内，天然不会入库"
```

## 数据边界

- 传给 API 的只有：统一缩放后的校园场景 JPEG（base64）和题目文本。不传文件名、路径、拍摄设备信息、
  账号信息，也不传任何个人身份数据。
- `data/image_manifest.csv` 记录的是原图的尺寸、字节数、SHA-256 与本地修改时间，用于证据链复核，
  不含 EXIF GPS。原图本身保留在本机 `F:\下载\多模态测试`，仓库内只放 2048px 高清副本。
- `data/results.jsonl` 保存模型原始回答，可能包含模型对场景的文字描述，但不含请求头/密钥。
- `data/network_errors.jsonl` 只保存错误文本（HTTP 状态码、异常类型、失败时间），不保存请求头、请求体或密钥；
  错误正文来自代理/服务端返回，工具在写盘前不回显 `Authorization` 头。
- 照片里出现的是校园公共场景与人群背影，工具不做人脸识别、不做身份推断。仓库**转公开前**应再人工过一遍
  `photos/`，若某张含可识别的清晰正脸或学号/工牌，改用裁剪版或替换样本。

## 万一泄漏了怎么办

1. 立刻到硅基流动控制台吊销该 key（不是改权限，是删除重建）；
2. 用新的 key 覆盖仓库外的 `.workbuddy/.siliconflow_key`；
3. 如果旧 key 已经进入过远端 commit 历史，仅删除文件不够 —— 需要轮换密钥并清理历史，
   但本仓库当前为**私有库**且从未提交过密钥，这一步暂不需要；
4. 检查控制台账单有无异常调用。

## 其他凭证

- GitHub 的 `.gh_token` 同样放在工作区根目录 `.workbuddy/`，用于本机 `api.github.com` 同步，
  与本课题无关，也从未入库。
- 课题 02 的 `tools/PowerProbe/signing/powerprobe.jks` 是**开发签名密钥**（口令公开在私有库内），
  **转公开前必须移除并改用 GitHub Actions Secrets**，这是另一个独立待办，见 `tools/PowerProbe/SECURITY.md`。
