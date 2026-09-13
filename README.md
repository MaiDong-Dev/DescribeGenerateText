# 面向 Text-to-SQL 的数据库描述自动生成

## 重要链接

🤖[Arxiv](https://arxiv.org/abs/2502.20657) |
📖[XiYan-SQL](https://github.com/XGenerationLab/XiYan-SQL) |

## 简介

当数据库没有显式的描述信息时，本仓库提供了一种自动生成有效数据库描述的方法。该方法采用「双过程」策略：先执行一个「从粗到细（coarse-to-fine）」的过程，再执行一个「从细到粗（fine-to-coarse）」的过程。在 Bird 基准上的实验结果表明，相比不使用描述，使用本方法生成的描述可将 SQL 生成准确率提升 0.93%，并达到了人类水平的 37% 的性能。

我们支持四种常见的数据库方言：SQLite、MySQL、PostgreSQL 和 SQL Server。

更多内容请阅读：[Arxiv](https://arxiv.org/abs/2502.20657)

<p align="center">
  <img src="https://github.com/XGenerationLab/XiYan-DBDescGen/blob/main/description_generation.png" alt="image" width="1000"/>
</p>

## 环境要求

+ python >= 3.9

你可以使用如下命令安装所需依赖包：

```shell
pip install -r requirements.txt
```

## 快速开始

1. 创建数据库连接。

以连接 SQLite 为例：

```python
import os
from sqlalchemy import create_engine

db_path = "path_to_sqlite"          # 数据库文件路径
abs_path = os.path.abspath(db_path) # 转为绝对路径
db_engine = create_engine(f'sqlite:///{abs_path}')  # 创建 SQLAlchemy 引擎
```

2. 配置 llama-index 的 LLM。

以阿里云百炼 dashscope 为例：

```python
from llama_index.llms.dashscope import DashScope, DashScopeGenerationModels
dashscope_llm = DashScope(model_name=DashScopeGenerationModels.QWEN_PLUS, api_key='YOUR API KEY HERE.')
```

3. 生成数据库描述并构建 M-Schema。

```python
from schema_engine import SchemaEngine

db_name = 'your_db_name'                    # 数据库名称
comment_mode = 'generation'                 # 描述生成模式
schema_engine_instance = SchemaEngine(db_engine, llm=dashscope_llm, db_name=db_name,
                                      comment_mode=comment_mode)
schema_engine_instance.fields_category()                          # 字段分类（维度/度量等）
schema_engine_instance.table_and_column_desc_generation()         # 生成表和列的描述
mschema = schema_engine_instance.mschema
mschema.save(f'./{db_name}.json')           # 保存 M-Schema 为 JSON
mschema_str = mschema.to_mschema()          # 转成文本形式的 M-Schema
print(mschema_str)
```

## 联系我们

如果你对我们的研究或产品感兴趣，欢迎随时联系我们。

#### 联系方式

Yifu Liu, zhencang.lyf@alibaba-inc.com

#### 加入我们的钉钉群

<a href="https://github.com/XGenerationLab/XiYan-SQL/blob/main/xiyansql_dingding.png">Ding Group 钉钉群</a>

## 引用

如果你觉得我们的工作有帮助，欢迎引用。

```bibtex
@article{description_generation,
      title={Automatic database description generation for Text-to-SQL},
      author={Yingqi Gao and Zhiling Luo},
      year={2025},
      eprint={2502.20657},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2502.20657},
}

@article{XiYanSQL,
      title={XiYan-SQL: A Novel Multi-Generator Framework For Text-to-SQL},
      author={Yifu Liu and Yin Zhu and Yingqi Gao and Zhiling Luo and Xiaoxia Li and Xiaorong Shi and Yuntao Hong and Jinyang Gao and Yu Li and Bolin Ding and Jingren Zhou},
      year={2025},
      eprint={2507.04701},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2507.04701},
}
```
