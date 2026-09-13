"""并行版 SchemaEngine。

ParallelSchemaEngine 继承自 SchemaEngine，将其中最耗时的两步——
字段分类（fields_category）与表/列描述生成（table_and_column_desc_generation）——
中相互独立的 LLM 调用拆分为多个子任务，交给线程池并行执行，从而显著
缩短整体运行时间。

注意：
- 字段分类阶段，每个字段的分类是相互独立的，可以按「字段」粒度并行。
- 描述生成阶段，每张表的列描述、表描述依赖数据库级信息 db_info（需先
  串行计算），因此 db_info 先算一次，随后按「表」粒度并行。
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from llama_index.core.llms import LLM

from schema_engine import SchemaEngine
from components import (
    field_category,
    generate_column_desc,
    generate_table_desc,
    understand_date_time_min_gran,
    understand_database,
    understand_fields_by_category,
)


class ParallelSchemaEngine(SchemaEngine):
    """并行执行字段分类与描述生成的 SchemaEngine 子类。"""

    def __init__(self, engine, max_workers: int = 4, **kwargs):
        """初始化。

        Args:
            engine: SQLAlchemy 引擎。
            max_workers: 线程池最大工作线程数。
            **kwargs: 其余参数透传给 SchemaEngine（llm、db_name、comment_mode 等）。
        """
        super().__init__(engine, **kwargs)
        self.max_workers = max_workers

    # ------------------------------------------------------------------
    # 字段分类（并行）
    # ------------------------------------------------------------------
    def fields_category(self):
        """并行地为所有表的所有字段做分类（DateTime/Enum/Code/Text/Measure）。"""
        # 先把所有 (表, 字段) 任务收集起来
        tasks = []
        for table_name in self._mschema.tables.keys():
            for field_name in self._mschema.tables[table_name]['fields'].keys():
                tasks.append((table_name, field_name))

        # 每个字段的分类互不依赖，直接并发
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._classify_single_field, table_name, field_name): (table_name, field_name)
                for table_name, field_name in tasks
            }
            for future in as_completed(futures):
                table_name, field_name = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"分类失败 {table_name}.{field_name}: {e}")

    def _classify_single_field(self, table_name: str, field_name: str):
        """对单个字段执行分类，并把结果写回 mschema。

        该逻辑与 SchemaEngine.fields_category 中内层循环完全一致，只是
        独立抽取成方法，方便在多个线程中并发调用。写回操作通过
        mschema 的 set_column_property 完成（字典操作，GIL 下安全）。
        """
        field_info = self._mschema.tables[table_name]['fields'][field_name]
        field_type = field_info['type']
        field_type_cate = self._type_engine.field_type_cate(field_type)
        field_info_str = self.get_single_field_info_str(table_name, field_name)

        # 调用 LLM 判定字段类别（category 与 dim_or_meas）
        res = field_category(field_type_cate, self._type_engine, self._llm,
                             field_info_str=field_info_str)

        # 日期时间字段：进一步推断最小时间颗粒度
        if res['category'] == self._type_engine.field_category_date_label:
            min_gran = understand_date_time_min_gran(field_info_str, llm=self._llm)
            if min_gran in self._type_engine.date_time_min_grans:
                self._mschema.set_column_property(table_name, field_name, "date_min_gran", min_gran)

        # 枚举字段：重新采样其所有枚举候选值
        if res['category'] == self._type_engine.field_category_enum_label:
            examples = self.get_column_value_examples(table_name, field_name)
            examples = [s for s in examples if s is not None and len(str(s)) > 0]
            self._mschema.set_column_property(table_name, field_name, "examples", examples)

        self._mschema.set_column_property(table_name, field_name, "category", res['category'])
        self._mschema.set_column_property(table_name, field_name, "dim_or_meas", res['dim_or_meas'])

    # ------------------------------------------------------------------
    # 表/列描述生成（并行）
    # ------------------------------------------------------------------
    def table_and_column_desc_generation(self, language: str = 'CN'):
        """并行生成所有表的列描述与表描述。

        与 SchemaEngine.table_and_column_desc_generation 的行为保持一致，
        只是将「每张表」的处理并发化。数据库级信息 db_info 仍先串行计算。
        """
        # 处理描述生成模式（origin/merge/generation/no_comment）
        if self.comment_mode == 'origin':
            return
        elif self.comment_mode == 'merge':
            pass
        elif self.comment_mode == 'generation':
            self._mschema.erase_all_column_comment()
            self._mschema.erase_all_table_comment()
        elif self.comment_mode == 'no_comment':
            self._mschema.erase_all_column_comment()
            self._mschema.erase_all_table_comment()
            return
        else:
            raise NotImplementedError(f"Unsupported comment mode {self.comment_mode}.")

        # 步骤1：先串行理解数据库整体信息（后续各表描述都要用到）
        db_mschema = self._mschema.to_mschema()
        db_info = understand_database(db_mschema, self._llm)
        self._mschema.db_info = db_info
        print("DB INFO: ", db_info)

        # 步骤2~4：按表并行生成列描述与表描述
        table_names = list(self._mschema.tables.keys())
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._generate_single_table, table_name, db_info, language): table_name
                for table_name in table_names
            }
            for future in as_completed(futures):
                table_name = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"生成描述失败 {table_name}: {e}")

    def _generate_single_table(self, table_name: str, db_info: str, language: str):
        """为单张表生成列描述与表描述（供多线程调用）。"""
        table_info = self._mschema.tables[table_name]
        fields = table_info['fields']

        table_comment = table_info.get('comment', '')
        # 已有较完整描述（>=10 字符）则不再生成表描述
        need_table_comment = len(table_comment) < 10

        table_mschema = self._mschema.single_table_mschema(table_name)

        # 取整表数据样例，转成 markdown 供 prompt 使用
        sql = self.get_all_field_examples(table_name, max_rows=10)
        res = self.fetch_truncated(sql, max_rows=10)
        res = self.trunc_result_to_markdown(res)

        # 步骤2：按维度/度量分组，理解同组字段间的区别与联系，作为补充信息
        supp_info = {}
        dim_fields = self._mschema.get_dim_or_meas_fields(self._type_engine.dimension_label, table_name)
        mea_fields = self._mschema.get_dim_or_meas_fields(self._type_engine.measure_label, table_name)
        if len(dim_fields) > 0:
            supp_info[self._type_engine.dimension_label] = understand_fields_by_category(
                db_info, table_name, table_mschema, self._llm, sql, res,
                dim_fields, self._type_engine.dimension_label)
        if len(mea_fields) > 0:
            supp_info[self._type_engine.measure_label] = understand_fields_by_category(
                db_info, table_name, table_mschema, self._llm, sql, res,
                mea_fields, self._type_engine.measure_label)

        # 步骤3：对每个缺少描述的列生成列描述
        for field_name, field_info in fields.items():
            field_info_str = self.get_single_field_info_str(table_name, field_name)
            dim_or_meas = field_info.get("dim_or_meas", '')
            field_desc = field_info.get('comment', '')
            if len(field_desc) == 0:
                field_desc = generate_column_desc(
                    field_name, field_info_str, table_mschema, self._llm,
                    sql, res, supp_info.get(dim_or_meas, ""), language=language)
                self._mschema.set_column_property(table_name, field_name, 'comment', field_desc)

        # 步骤4：若需要则生成表描述
        table_mschema = self._mschema.single_table_mschema(table_name)
        if need_table_comment:
            table_desc = generate_table_desc(table_name, table_mschema, self._llm,
                                             sql, res, language=language)
            self._mschema.set_table_property(table_name, 'comment', table_desc)
