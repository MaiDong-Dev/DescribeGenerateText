# 项目解读指南（XiYan-DBDescGen）

> 面向 Text-to-SQL 的数据库描述自动生成

## 1. 项目是什么

本项目解决的问题：**当一个数据库没有显式的表/列注释时，如何自动为它生成高质量的、能被大模型有效利用的描述**，从而提升 Text-to-SQL（自然语言转 SQL）的准确率。

核心思想（论文 arXiv:2502.20657）是一个「双过程」方法：

1. **粗到细（coarse-to-fine）**：先理解整个数据库 → 再理解每张表 → 再到每个字段。
2. **细到粗（fine-to-coarse）**：从每个字段的细节（类型、样例、统计量）出发，逐步向上归纳出字段描述、表描述，最终拼出完整的数据库描述。

在 Bird 基准上，相比不用描述，该方法将 SQL 生成准确率提升 0.93%，达到人类水平的 37%。

## 2. 核心概念：M-Schema

M-Schema 是项目最关键的数据结构，它是对数据库 schema 的「增强版」描述，在标准 schema（表名、列名、类型）基础上，额外补充了：

- 字段的**语义类别**：`Code`（编码）、`Enum`（枚举）、`Text`（文本）、`Measure`（度量）、`DateTime`（日期时间）。
- 字段的**维度/度量**属性：`Dimension`（维度）或 `Measure`（度量）。
- 字段的**描述**（中文/英文）、**表描述**。
- 主键、外键、唯一键、索引、可空性、默认值等元信息。
- 字段的**统计量**：COUNT、COUNT(DISTINCT)、MAX、MIN、AVG、字符长度等。
- 字段的**取值样例**（Value Examples）。
- 日期时间字段的**最小颗粒度**（YEAR/MONTH/DAY/...）。

M-Schema 的最终形态是一段文本（`to_mschema()`），可以直接作为 prompt 交给下游的 SQL 生成模型使用。

## 3. 代码结构

```
d:/Projectfiler/DescribeGenerateText/
├── main.py                      # 最小示例入口（串行）
├── parallel_main.py             # 命令行入口（支持串行/并行）
├── schema_engine.py             # 核心引擎：读取 DB、构建 M-Schema、分类、生成描述
├── parallel_schema_engine.py    # 并行版引擎（新增，继承 SchemaEngine）
├── mschema.py                   # M-Schema 数据结构（表/字段/外键的增删改查与序列化）
├── type_engine.py               # 类型引擎：数据库方言、字段类型/类别的常量定义
├── components.py                # 各类 LLM 原子能力（分类、生成描述、理解数据库等）
├── call_llamaindex_llm.py       # LLM 调用封装（重试、JSON 校验）
├── default_prompts.py           # 所有 prompt 模板（中文提示词）
├── utils.py                     # 工具函数（JSON 读写、SQL/JSON 解析、样例清洗）
├── requirements.txt             # 依赖清单
├── v6-duckdb/
│   └── parallel_llm_processor.py # 通用并行 LLM 处理器（带限速、重试、缓存）
├── README.md                    # 英文原版说明
└── README_CN.md                 # 中文翻译（本次新增）
```

### 模块职责与依赖关系

```
main.py / parallel_main.py
        │
        ▼
  schema_engine.py (SchemaEngine)  ──►  parallel_schema_engine.py (ParallelSchemaEngine)
        │ 依赖
        ├── mschema.py   (MSchema)
        ├── type_engine.py (TypeEngine)
        ├── components.py (field_category / generate_*_desc / understand_*)
        ├── utils.py     (examples_to_str 等)
        └── call_llamaindex_llm.py (call_llm / call_llm_with_json_validation)

components.py 依赖 default_prompts.py（prompt 模板）+ call_llamaindex_llm.py
v6-duckdb/parallel_llm_processor.py 依赖 call_llamaindex_llm.py（call_llm_with_json_validation）
```

## 4. 解读步骤（代码执行流程）

### 第 0 步：初始化

1. 用 SQLAlchemy `create_engine` 建立数据库连接。
2. 初始化大模型（如 DashScope 的 QWEN-PLUS）。
3. 创建 `SchemaEngine(engine, llm=..., db_name=..., comment_mode=...)`。

`SchemaEngine` 继承自 llama-index 的 `SQLDatabase`，构造函数中：

- 过滤出可用的表（`_usable_tables`）。
- 记录数据库方言（`_dialect`），并用 `TypeEngine` 校验是否支持。
- 创建 `MSchema` 并调用 `init_mschema()` 读取数据库真实结构。

### 第 1 步：`init_mschema()` —— 读取数据库结构

对每张表，读取：

- 表注释、主键、唯一键、索引、外键。
- 每个字段的类型、注释、是否主键/唯一/可空、默认值、自增。
- 每个字段的**取值样例**（`SELECT DISTINCT ... LIMIT 5`）。

把以上信息写入 `MSchema.tables`，形成「增强版 schema」的基础骨架。

### 第 2 步：`fields_category()` —— 字段分类（粗到细）

对每个字段：

1. 用 `TypeEngine.field_type_cate` 判断基础类型分类（Number/String/DateTime/Bool/Other）。
2. 组装字段完整信息（`get_single_field_info_str`：含统计量、样例等）。
3. 调用 `components.field_category` 判定语义类别：
   - DateTime → 日期时间；Bool → 枚举；
   - 其他类型先问 LLM「是否日期时间」；
   - 否则按字符串/数值/未知类型，区分 `enum/code/text/measure`。
4. 日期时间字段 → 进一步推断最小颗粒度。
5. 枚举字段 → 重新采样全部候选值。
6. 将 `category` 与 `dim_or_meas` 写回 M-Schema。

### 第 3 步：`table_and_column_desc_generation()` —— 生成描述（细到粗）

1. **处理 comment_mode**（origin/merge/generation/no_comment）。
2. **理解数据库**：`understand_database` 先生成整体概要，再补充领域知识。
3. 对每张表：
   - 取整表样例数据并转成 markdown。
   - 按维度/度量分组，用 `understand_fields_by_category` 理解组内字段关系（补充信息）。
   - 对每个缺描述的列，用 `generate_column_desc` 生成列描述。
   - 若表缺描述，用 `generate_table_desc` 生成表描述。

### 第 4 步：输出

- `mschema.save(path)` 保存为 JSON。
- `mschema.to_mschema()` 生成文本形式的 M-Schema，直接用于下游 SQL 生成。

## 5. 并行版本说明

`ParallelSchemaEngine`（`parallel_schema_engine.py`）继承 `SchemaEngine`，将两个耗时步骤并行化：

- **字段分类**：每个字段的分类相互独立 → 按「字段」粒度并行。
- **描述生成**：数据库级信息 `db_info` 先串行算一次，之后按「表」粒度并行。

通过 `parallel_main.py --parallel --max_workers N` 即可使用。

此外 `v6-duckdb/parallel_llm_processor.py` 提供了更通用的 `ParallelLLMProcessor`，支持限速、指数退避重试、结果缓存与 JSON 校验（依赖本次新增的 `call_llm_with_json_validation`）。

## 6. 快速运行

```shell
pip install -r requirements.txt

# 串行（默认）
python parallel_main.py --db_path ./book_1.sqlite --api_key "你的key"

# 并行
python parallel_main.py --parallel --max_workers 8 --db_path ./book_1.sqlite --api_key "你的key"
```

## 7. 本次补全/修复内容

| 文件 | 变更 |
|------|------|
| `parallel_schema_engine.py` | **新增**，补全 `parallel_main.py` 所依赖的 `ParallelSchemaEngine` |
| `call_llamaindex_llm.py` | 新增 `call_llm_with_json_validation`（`parallel_llm_processor.py` 依赖），并补充注释 |
| `type_engine.py` | 修复 `def __int__` → `def __init__`（构造函数拼写错误） |
| `schema_engine.py` | 修复枚举样例过滤 bug（`len(str(examples))` → `len(str(s))`） |
| `utils.py` | 修复 `examples_to_str` 中 datetime/date 判断顺序问题，并简化逻辑 |
| `main.py` / `parallel_main.py` / `components.py` / `schema_engine.py` | 补充详细中文注释 |
| `README_CN.md` | 新增中文 README 翻译 |
