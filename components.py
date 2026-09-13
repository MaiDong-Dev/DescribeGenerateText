from llama_index.core.llms import LLM
from typing import Any, Dict, Iterable, List, Optional, Tuple
from utils import extract_sql_from_llm_response, extract_simple_json_from_qwen
from default_prompts import (
    DEFAULT_IS_DATE_TIME_FIELD_PROMPT,
    DEFAULT_NUMBER_CATEGORY_FIELD_PROMPT,
    DEFAULT_STRING_CATEGORY_FIELD_PROMPT,
    DEFAULT_UNKNOWN_FIELD_PROMPT,
    DEFAULT_COLUMN_DESC_GEN_CHINESE_PROMPT,
    DEFAULT_COLUMN_DESC_GEN_ENGLISH_PROMPT,
    DEFAULT_TABLE_DESC_GEN_CHINESE_PROMPT,
    DEFAULT_TABLE_DESC_GEN_ENGLISH_PROMPT,
    DEFAULT_UNDERSTAND_FIELDS_BY_CATEGORY_PROMPT,
    DEFAULT_UNDERSTAND_DATABASE_PROMPT,
    DEFAULT_GET_DOMAIN_KNOWLEDGE_PROMPT,
    DEFAULT_DATE_TIME_MIN_GRAN_PROMPT,
    DEFAULT_SQL_GEN_PROMPT
)
from call_llamaindex_llm import call_llm, call_llm_message
from type_engine import TypeEngine


def understand_date_time_min_gran(field_info_str: str = '', llm: Optional[LLM] = None):
    """推断日期时间字段的最小时间颗粒度。

    通过 LLM 分析字段的取值样例，判断该字段能精确到的最小时间单位
    （如 YEAR/MONTH/DAY/HOUR/MINUTE/SECOND 等）。

    Args:
        field_info_str: 某个字段的结构化信息文本（字段名、类型、样例等）。
        llm: 大模型实例。

    Returns:
        大写并去除首尾空白后的最小颗粒度名称，例如 "MONTH"。
    """
    res = call_llm(
        prompt=DEFAULT_DATE_TIME_MIN_GRAN_PROMPT,
        llm=llm,
        field_info_str=field_info_str
    )
    return res.upper().strip()


def understand_database(db_mschema: str = '', llm: Optional[LLM] = None):
    """理解整个数据库：先生成概要，再补充领域知识。

    分为两步：
        1. 调用 LLM 对数据库 schema 做整体理解，总结其存储的数据领域；
        2. 基于第一步的总结，再调用 LLM 获取该领域人们通常关心的维度与指标。

    Args:
        db_mschema: 数据库的 M-Schema 文本。
        llm: 大模型实例。

    Returns:
        拼接后的数据库理解文本（概要 + 领域知识）。
    """
    db_info1 = call_llm(DEFAULT_UNDERSTAND_DATABASE_PROMPT, llm, db_mschema=db_mschema)
    db_info2 = call_llm(DEFAULT_GET_DOMAIN_KNOWLEDGE_PROMPT, llm, db_info=db_info1)
    return (db_info1 + '\n' + db_info2).strip()


def generate_column_desc(field_name: str, field_info_str: str = '', table_mschema: str = '',
        llm: Optional[LLM] = None, sql: Optional[str] = None, sql_res: Optional[str] = None,
        supp_info: Optional[str] = None, language: Optional[str] = 'CN'):
    """为单个字段（列）生成描述。

    Args:
        field_name: 字段名。
        field_info_str: 该字段的结构化信息文本。
        table_mschema: 所属表的 M-Schema 文本。
        llm: 大模型实例。
        sql: 获取该表样例数据的 SQL（供 prompt 展示）。
        sql_res: 该 SQL 的查询结果（markdown 表格）。
        supp_info: 补充信息（同维度/度量字段之间的关系理解）。
        language: 描述语言，'CN' 或 'EN'。

    Returns:
        清洗后的字段描述文本。
    """
    # 根据语言选择中文或英文的 prompt 模板
    if language == 'CN':
        prompt = DEFAULT_COLUMN_DESC_GEN_CHINESE_PROMPT
    elif language == 'EN':
        prompt = DEFAULT_COLUMN_DESC_GEN_ENGLISH_PROMPT
    else:
        raise NotImplementedError(f'Unsupported language {language}.')

    # 调用 LLM 生成字段描述（prompt 要求以 JSON 形式返回）
    column_desc = call_llm(
        prompt,
        llm,
        table_mschema=table_mschema,
        sql=sql,
        sql_res=sql_res,
        field_name=field_name,
        field_info_str=field_info_str,
        supp_info=supp_info
    ).strip()

    # 从返回的 JSON 中提取描述字段，并做格式清洗
    if language == 'CN':
        column_desc = extract_simple_json_from_qwen(column_desc).get('chinese_name', '')
        # 去掉多余引号、markdown 加粗符号
        column_desc = column_desc.replace('"', '').replace('“', '').replace('”', '').replace('**', '')
        if column_desc.endswith('。'):
            column_desc = column_desc[:-1].strip()
    elif language == 'EN':
        column_desc = extract_simple_json_from_qwen(column_desc).get('english_desc', '')
        column_desc = column_desc.strip()
    # 去掉开头的冒号
    if column_desc.startswith(':') or column_desc.startswith('：'):
        column_desc = column_desc[1:].strip()
    # 只取第一行（防止模型输出多行）
    column_desc = column_desc.split('\n')[0]

    return column_desc.strip()

def generate_table_desc(table_name: str, table_mschema: str = '',
        llm: Optional[LLM] = None, sql: Optional[str] = None, sql_res: Optional[str] = None,
        language: Optional[str] = 'CN'):
    """为整张表生成描述。

    Args:
        table_name: 表名。
        table_mschema: 该表的 M-Schema 文本。
        llm: 大模型实例。
        sql: 获取该表样例数据的 SQL。
        sql_res: 该 SQL 的查询结果（markdown 表格）。
        language: 描述语言，'CN' 或 'EN'。

    Returns:
        清洗后的表描述文本。
    """
    if language == 'CN':
        prompt = DEFAULT_TABLE_DESC_GEN_CHINESE_PROMPT
    elif language == 'EN':
        prompt = DEFAULT_TABLE_DESC_GEN_ENGLISH_PROMPT
    else:
        raise NotImplementedError(f'Unsupported language {language}.')

    # 调用 LLM 生成表描述，并从返回的 JSON 中提取 table_desc
    table_desc = call_llm(
        prompt,
        llm,
        table_name=table_name,
        table_mschema=table_mschema,
        sql=sql,
        sql_res=sql_res
    )
    table_desc = extract_simple_json_from_qwen(table_desc).get('table_desc', '')
    table_desc = table_desc.strip()

    return table_desc.strip()


def understand_fields_by_category(db_info: str, table_name: str, table_mschema: str = '',
        llm: Optional[LLM] = None, sql: Optional[str] = None, sql_res: Optional[str] = None,
        fields: Optional[List] = [], dim_or_meas: str = ''):
    """按类别理解同一组字段之间的区别与联系。

    将同一类（例如都是维度、或都是度量）的字段放到一起，让 LLM 分析
    它们之间的语义关系，作为后续生成描述时的补充参考信息。

    Args:
        db_info: 数据库整体理解文本。
        table_name: 表名。
        table_mschema: 表的 M-Schema 文本。
        llm: 大模型实例。
        sql: 样例数据 SQL。
        sql_res: 样例数据结果。
        fields: 该类别的字段名列表。
        dim_or_meas: 类别（Dimension 或 Measure）。

    Returns:
        LLM 分析出的字段间关系文本。
    """
    text = call_llm(
        DEFAULT_UNDERSTAND_FIELDS_BY_CATEGORY_PROMPT,
        llm,
        db_info=db_info,
        table_name=table_name,
        table_mschema=table_mschema,
        sql=sql,
        sql_res=sql_res,
        fields='、'.join([f"{field}" for field in fields]),
        category=dim_or_meas
    )
    return text


def field_category(field_type_cate: str, type_engine: TypeEngine, llm: Optional[LLM] = None,
                   field_info_str: str = ''):
    """判定字段的语义类别（Code/Enum/Text/Measure/DateTime）以及维度/度量属性。

    这是一个「由粗到细」的判定流程，根据字段的基础类型分类（field_type_cate），
    走不同的分支：
        - DateTime 类型：直接判定为日期时间类。
        - Bool 类型：直接判定为枚举类。
        - 其他类型：先用 LLM 判断是否为日期时间；若不是，再根据字符串/数值/
          未知类型，调用对应的 prompt 区分 enum/code/text/measure。

    Args:
        field_type_cate: 字段的基础类型分类（Number/String/DateTime/Bool/Other）。
        type_engine: TypeEngine 实例，提供各类标签常量。
        llm: 大模型实例。
        field_info_str: 字段的结构化信息文本。

    Returns:
        dict，形如 {"category": "Enum", "dim_or_meas": "Dimension"}。
    """
    # 预定义各种判定结果的映射，避免在每个分支重复构造
    code_res = {"category": type_engine.field_category_code_label,
                "dim_or_meas": type_engine.dimension_label}
    enum_res = {"category": type_engine.field_category_enum_label,
                'dim_or_meas': type_engine.dimension_label}
    date_res = {"category": type_engine.field_category_date_label,
                'dim_or_meas': type_engine.dimension_label}
    measure_res = {"category": type_engine.field_category_measure_label,
                   'dim_or_meas': type_engine.measure_label}
    text_res = {"category": type_engine.field_category_text_label,
                'dim_or_meas': type_engine.dimension_label}

    # 日期时间类型 / 布尔类型：无需 LLM，直接返回
    if field_type_cate == type_engine.field_type_date_label:
        return date_res
    elif field_type_cate == type_engine.field_type_bool_label:
        return enum_res
    else:
        # 其他类型：先询问 LLM 该字段是否属于日期时间
        kwargs = {"llm": llm, "field_info_str": field_info_str}
        is_date_time = call_llm(
            DEFAULT_IS_DATE_TIME_FIELD_PROMPT, **kwargs
        ).strip()
        if is_date_time == '是':
            return date_res
        else:
            if field_type_cate == type_engine.field_type_string_label:
                # 非时间日期类字符串：判断是 code、text 还是 enum
                res = call_llm(
                    DEFAULT_STRING_CATEGORY_FIELD_PROMPT, **kwargs
                ).strip().lower()
                if res == 'enum':
                    return enum_res
                elif res == 'text':
                    return text_res
                else:
                    return code_res
            elif field_type_cate == type_engine.field_type_number_label:
                # 非时间日期类的数值：判断是 code、measure 还是 enum
                res = call_llm(DEFAULT_NUMBER_CATEGORY_FIELD_PROMPT, **kwargs).strip().lower()
                if res == 'enum':
                    return enum_res
                elif res == 'measure':
                    return measure_res
                else:
                    return code_res
            else:
                # 未知类型：判断是 enum、measure、text 还是 code
                res = call_llm(DEFAULT_UNKNOWN_FIELD_PROMPT, **kwargs).strip().lower()
                if res == 'enum':
                    return enum_res
                elif res == 'measure':
                    return measure_res
                elif res == 'text':
                    return text_res
                else:
                    return code_res
    code_res = {"category": type_engine.field_category_code_label,
                "dim_or_meas": type_engine.dimension_label}
    enum_res = {"category": type_engine.field_category_enum_label,
                'dim_or_meas': type_engine.dimension_label}
    date_res = {"category": type_engine.field_category_date_label,
                'dim_or_meas': type_engine.dimension_label}
    measure_res = {"category": type_engine.field_category_measure_label,
                   'dim_or_meas': type_engine.measure_label}
    text_res = {"category": type_engine.field_category_text_label,
                'dim_or_meas': type_engine.dimension_label}

    if field_type_cate == type_engine.field_type_date_label:
        return date_res
    elif field_type_cate == type_engine.field_type_bool_label:
        return enum_res
    else:
        kwargs = {"llm": llm, "field_info_str": field_info_str}
        is_date_time = call_llm(
            DEFAULT_IS_DATE_TIME_FIELD_PROMPT, **kwargs
        ).strip()
        if is_date_time == '是':
            return date_res
        else:
            if field_type_cate == type_engine.field_type_string_label:
                # 非时间日期类字符串，判断是code、text还是enum
                res = call_llm(
                    DEFAULT_STRING_CATEGORY_FIELD_PROMPT, **kwargs
                ).strip().lower()
                if res == 'enum':
                    return enum_res
                elif res == 'text':
                    return text_res
                else:
                    return code_res
            elif field_type_cate == type_engine.field_type_number_label:
                # 非时间日期类的数值，判断是code、measure还是enum
                res = call_llm(DEFAULT_NUMBER_CATEGORY_FIELD_PROMPT, **kwargs).strip().lower()
                if res == 'enum':
                    return enum_res
                elif res == 'measure':
                    return measure_res
                else:
                    return code_res
            else:
                res = call_llm(DEFAULT_UNKNOWN_FIELD_PROMPT, **kwargs).strip().lower()
                if res == 'enum':
                    return enum_res
                elif res == 'measure':
                    return measure_res
                elif res == 'text':
                    return text_res
                else:
                    return code_res


def dummy_sql_generator(dialect: str, db_mschema: str, question: str, evidence: str = '',
                  llm: Optional[LLM] = None) -> None or str:
    """根据数据库 schema 和用户问题，生成一条可执行的 SQL（Text-to-SQL）。

    这是一个简化版的 SQL 生成器（dummy 意为占位/示例），主要用于演示
    生成的 M-Schema 如何支撑下游的 SQL 生成任务。

    Args:
        dialect: 数据库方言（如 sqlite/mysql/postgresql）。
        db_mschema: 数据库的 M-Schema 文本。
        question: 用户自然语言问题。
        evidence: 参考信息/证据（可选）。
        llm: 大模型实例。

    Returns:
        从 LLM 返回中解析出的 SQL 语句。
    """
    kwargs = {"dialect": dialect, "db_mschema": db_mschema,
              "question": question, "evidence": evidence}
    llm_response = call_llm(DEFAULT_SQL_GEN_PROMPT, llm, **kwargs)
    # 从 markdown 格式的 LLM 回复中提取 ```sql 代码块
    sql = extract_sql_from_llm_response(llm_response)
    return sql
