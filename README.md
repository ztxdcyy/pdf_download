# Paperfetch

输入关键词，自动生成可直接粘贴的参考文献 citation，并尝试下载可访问的 PDF（优先 arXiv）。  
默认把 citation 追加到 `citations/YYYY-MM-DD.txt`，方便每天积累。

## 开箱即用（推荐）

```bash
# 1) 安装 uv 并创建虚拟环境
uv venv
source .venv/bin/activate

# 2) 安装本项目
uv pip install -e .

# 3) 创建并填写配置
cp config.example.json config.local.json

# 4) 开跑
paperfetch DETR
```

> 轻松上手，开箱即用。默认会下载可访问的 PDF。

## 你能得到什么

- 按 GB/T 7714-2015 常见类型模板导出的 citation（重点覆盖 `J/C/M/D/R/EB/OL`）
- 当天自动追加的 citation 文件（`YYYY-MM-DD.txt`，自动连续编号）
- 可访问的 PDF 自动下载（默认启用，优先 arXiv）
- 可扩展：支持接入机构订阅目录源（规划中）

## 使用方式

```bash
# 默认：all + LLM（S2 + OpenAlex + arXiv）
paperfetch DETR

# 带空格关键词（不加引号也可）
paperfetch Focal loss for dense object detection

# 仅用 arXiv 做标题检索
paperfetch MME: A Comprehensive Evaluation Benchmark for Multimodal Large Language Models --provider arxiv

# 只要 citation，不下载 PDF
paperfetch DETR --no-download-pdf

# Python 模块方式
python -m paperfetch DETR
```

## 配置

复制模板并填写自己的 key/email：

```bash
cp config.example.json config.local.json
```

`config.local.json` 示例：

```json
{
  "llm": {
    "base_url": "https://open.bigmodel.cn/api/paas/v4/",
    "api_key": "YOUR_LLM_API_KEY",
    "model": "glm-5",
    "disable_reasoning": true,
    "system_prompt": "Prefer highly cited canonical papers; prioritize conference versions over preprints when both exist."
  },
  "providers": {
    "s2_api_key": "YOUR_S2_API_KEY",
    "openalex_email": "you@example.com"
  }
}
```

`llm.system_prompt` 为可选项，用于注入你的检索偏好（例如优先综述/优先首发论文/优先近五年）。该提示会同时作用于：
- LLM 标题提议阶段
- LLM 候选池重排阶段

> `config.local.json` 不建议提交到 GitHub（已加入 `.gitignore`）。
> 配置加载会先读取 `config.example.json` 作为默认值，再用 `config.local.json`（或 `PAPERFETCH_CONFIG_FILE` 指定文件）覆盖同名字段。

## 关键参数

- `--provider`：`all | auto | s2 | openalex | arxiv`（默认 `all`）
- `--min-title-sim`：LLM 第 1 标题与最终候选的相似度阈值（默认 `0.6`）
- `--download-pdf` / `--no-download-pdf`：开关 PDF 下载
- `--pdf-arxiv-fallback` / `--no-pdf-arxiv-fallback`：下载失败时是否回退 arXiv（默认启用）
- `--out`：citation 输出目录（默认 `./citations`）
- `--pdf-out`：PDF 输出目录（默认 `./papers`）
- `--notify-sound` / `--no-notify-sound`：任务结束播放提示音（默认启用）
- `--success-sound` / `--warning-sound` / `--failure-sound`：成功/警告/失败音效名（macOS 系统音，如 `Glass`、`Ping`、`Basso`）

任务状态判定（用于提示音与退出码）：
- 默认优先按 PDF 下载结果判断
- 下载成功：`success`（退出码 `0`）
- 使用 `--no-download-pdf`：`warning`（退出码 `0`）
- 启用下载但 PDF 失败：`failure`（退出码 `2`）

## 输出示例

```text
[1] Author A, Author B, et al. Title[J]. Journal, Year, Volume(Issue): Pages.
[2] Author A, Author B, et al. Title[EB/OL]. (PublishDate)[AccessDate]. URL.
```

## 已知限制

- PDF 下载仅依赖公开可访问链接，不保证所有论文可下载（受版权/OA状态限制）。
- 检索质量依赖 provider 与 LLM 提议，建议最终人工复核。
- 机构订阅源仍在规划中，欢迎提出需求细节。
