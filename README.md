# Keyword Citation Collector

基于“LLM 标题提议 + 标题检索池 + 池内选择”的参考文献收集工具。  
输入一个关键词，自动生成一条可直接粘贴到论文参考文献区域的 citation，并按日期追加写入本地文本文件。

## 开箱即用

```bash
# 1) 创建虚拟环境（uv）
uv venv
source .venv/bin/activate

# 2) 安装本项目
uv pip install -e .

# 3) 创建并填写配置
cp config.example.json config.local.json

# 4) 直接开跑
paperfetch DETR
```

> 轻松上手，开箱即用。默认会自动下载可访问的 PDF。

## 项目目标

- 默认输出 citation + 下载 PDF（开放获取）
- 尽量命中“原始/首发”论文，而非后续改进版本
- 保留可追溯的最小元信息，便于后续人工复核

## 核心流程

1. 调用 LLM 提议 1~3 个“可能的原始论文标题”（仅用于选文，不直接生成 citation 文本）。
2. 用 LLM 提议标题在 provider 内检索，形成候选池（pool）。
3. 池内选择：交给 LLM 选 1 条；再计算与 **LLM 第 1 标题** 的相似度，低于阈值直接失败。
4. 选中文献后，自动用另一检索源做一次元数据补全（`OpenAlex ↔ S2` 互补）。
5. 将 citation 追加到 `citations/YYYY-MM-DD.txt`。

## 项目结构

- `paperfetch/cli.py`：CLI 入口与主流程编排
- `paperfetch.py`：兼容入口（调用 `paperfetch/cli.py`）
- `paperfetch/config.py`：统一配置加载（LLM + S2 + OpenAlex）
- `paperfetch/title_llm.py`：LLM 标题提议与接口调用
- `paperfetch/select.py`：标题相似度计算
- `paperfetch/rerank_llm.py`：LLM 池内选择
- `paperfetch/openalex.py`：OpenAlex 检索与字段映射
- `paperfetch/s2.py`：Semantic Scholar 检索
- `paperfetch/pdf.py`：PDF 候选链接抽取与下载
- `paperfetch/citation.py`：citation 格式化与按日期追加
- `config.example.json`：配置模板（提交到 GitHub）
- `config.local.json`：本地配置（不提交）

## 环境要求

- Python `>=3.9`
- 可访问 LLM 接口与检索接口

## 安装

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

## 配置

默认读取项目根目录 `config.local.json`（由 `config.example.json` 复制而来）：

```json
{
  "llm": {
    "base_url": "https://open.bigmodel.cn/api/paas/v4/",
    "api_key": "YOUR_LLM_API_KEY",
    "model": "glm-5",
    "disable_reasoning": true
  },
  "providers": {
    "s2_api_key": "YOUR_S2_API_KEY",
    "openalex_email": "you@example.com"
  }
}
```

### 配置方式

```bash
cp config.example.json config.local.json
# 编辑 config.local.json，填写你自己的 key/email
```

可选：通过环境变量 `PAPERFETCH_CONFIG_FILE` 指定其它配置文件路径。

> 安全建议：不要将真实 API Key 提交到公开仓库；`config.local.json` 建议仅本地保存。
> S2 免费配额通常较严格（例如 1 req/s）；程序已内置节流以降低 429 概率。

## 使用方式

```bash
# 默认：all + llm
paperfetch DETR

# 支持带空格关键词（不加引号也可）
paperfetch Focal loss for dense object detection

# 缩写关键词推荐提高召回规模
paperfetch DETR --provider all --limit 80 --llm-candidates 20 --llm-timeout 90

# 只用 arXiv 做标题检索
paperfetch MME: A Comprehensive Evaluation Benchmark for Multimodal Large Language Models --provider arxiv

# 对照模式（不使用 LLM）
paperfetch DETR --selector rule

# 如需只输出 citation，不下载 PDF
paperfetch DETR --no-download-pdf

# 也可用 python -m 方式
python -m paperfetch DETR
```

## CLI 参数

- `keyword`：查询关键词（必填，支持空格字符串）
- `--out`：输出目录（默认 `./citations`）
- `--limit`：初始检索候选上限（默认 `50`）
- `--provider`：检索源（`all | auto | s2 | openalex | arxiv`，默认 `all`）
- `--selector`：选择策略（`llm | rule`，默认 `llm`）
- `--llm-candidates`：强校验候选池大小（默认 `10`）
- `--llm-timeout`：LLM 请求超时（秒，默认 `90`）
- `--min-title-sim`：LLM 第 1 标题与最终候选的相似度阈值（默认 `0.6`）
- `--download-pdf`：启用 PDF 下载（默认已启用）
- `--no-download-pdf`：关闭 PDF 下载
- `--pdf-out`：PDF 输出目录（默认 `./papers`）
- `--pdf-timeout`：每个 PDF 下载请求超时（默认 `45` 秒）
- `--pdf-arxiv-fallback`：PDF 下载失败时自动尝试 arXiv（默认已启用）
- `--no-pdf-arxiv-fallback`：关闭 arXiv 回退

## 输出格式

每条记录第一行为可直接引用的参考文献行（不自动添加编号）。  
citation 由检索元数据模板化生成（非 LLM 直接自由生成），当前按文献类型输出 `[J]/[C]/[M]/[D]/[R]/...` 标识：

```text
Author A, Author B, et al. Title[J]. Journal, Year, Volume(Issue): Pages.
Author A, Author B, et al. Title[C]. Conference, Year: Pages.
```

后续附带简化 `meta` 行（关键词、来源、匹配信息、置信度等）用于追踪与复核。

文献类型优先使用检索源结构化字段；若缺失，会基于 `venue/title/doi` 做保守启发式判定（例如会议关键词映射为 `[C]`）。
此外会尝试用另一检索源回填 `venue/documentType/pages` 等字段，减少 `Unknown Conference/Unknown Source`。

## 调试

```bash
export LLM_DEBUG=1
paperfetch DETR --provider all --limit 80 --llm-candidates 20 --llm-timeout 90
```

## 已知限制

- 已支持按检索元数据区分常见文献类型（如期刊 `[J]`、会议 `[C]`）。
- 受限于检索源字段完整度，部分 GB/T 7714 字段（出版地、出版者等）可能缺失，建议最终人工复核。
- PDF 下载仅依赖公开可访问链接，不保证所有论文可下载（受版权/OA状态限制）。
- 结果质量依赖检索召回与 LLM 提议质量，仍建议人工最终确认。
