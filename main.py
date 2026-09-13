"""项目最小示例入口：演示如何用 SchemaEngine 生成数据库描述。

执行流程：
    1. 初始化 DashScope LLM（大模型）
    2. 建立 SQLite 数据库连接
    3. 创建 SchemaEngine，读取数据库 schema 并构建 M-Schema
    4. 对字段做分类（维度/度量、Code/Enum/Text 等）
    5. 生成表和列的中文描述
    6. 保存并打印最终的 M-Schema
"""
import os
from llama_index.llms.dashscope import DashScope, DashScopeGenerationModels
from sqlalchemy import create_engine
from schema_engine import SchemaEngine

# 1. 初始化大模型（以阿里云百炼 DashScope 的 QWEN-PLUS 为例）
dashscope_llm = DashScope(
    model_name=DashScopeGenerationModels.QWEN_PLUS,
    api_key=os.getenv('QWEN_API_KEY'))

# 2. 建立数据库连接（SQLite 需使用绝对路径）
db_path = 'D:/Projectfiler/Meta-Builder-Agent/data/metadata.db'
db_abs_path = os.path.abspath(db_path)
db_engine = create_engine(f'sqlite:///{db_abs_path}')

# 3. 创建 SchemaEngine
#    comment_mode='generation' 表示：清除库中原有描述，完全由模型重新生成。
#    其他可选值：'origin'（保持库中描述）、'merge'（仅补缺）、'no_comment'（不要描述）。
comment_mode = 'generation'
schema_engine_instance = SchemaEngine(db_engine, llm=dashscope_llm, db_name='book_1',
                                      comment_mode=comment_mode)

# 4. 字段分类：为每列标注类别与维度/度量属性
schema_engine_instance.fields_category()

# 5. 生成表描述与列描述
schema_engine_instance.table_and_column_desc_generation()

# 6. 取出 M-Schema，保存为 JSON 并打印文本形式
mschema = schema_engine_instance.mschema
mschema.save('./book_1.json')
mschema_str = mschema.to_mschema()
print(mschema_str)