import re
import datetime, decimal
import json


def write_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data


def read_text(filename)->str:
    data = []
    with open(filename, 'r', encoding='utf-8') as file:
        for line in file.readlines():
            line = line.strip()
            data.append(line)
    return data


def save_raw_text(filename, content):
    with open(filename, 'w', encoding='utf-8') as file:
        file.write(content)


def save_json(target_file,js,indent=4):
    with open(target_file, 'w', encoding='utf-8') as f:
        json.dump(js, f, ensure_ascii=False, indent=indent)


def is_email(string):
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    match = re.match(pattern, string)
    if match:
        return True
    else:
        return False


def extract_sql_from_llm_response(llm_response: str) -> str:
    """
    Parse SQL from LLM response in markdown format
    """

    sql = llm_response
    pattern = r"```sql(.*?)```"

    sql_code_snippets = re.findall(pattern, llm_response, re.DOTALL)

    if len(sql_code_snippets) > 0:
        sql = sql_code_snippets[-1].strip()

    return sql


def examples_to_str(examples: list) -> list[str]:
    """把字段的取值样例统一转换成字符串列表，并过滤敏感/无意义值。

    处理规则：
    - 日期/时间类型：只保留一个样例（避免多个日期干扰描述生成）。
    - Decimal：转为浮点数字符串。
    - 邮箱/URL：视为敏感或噪声，直接丢弃整组样例。
    - 其他非字符串（如 int/float）：保持不变，最后统一 str()。

    注意：datetime.datetime 是 datetime.date 的子类，因此必须先判断
    datetime 再判断 date，否则分支会被 date 提前命中（原代码顺序有误）。
    """
    values = examples
    for i in range(len(values)):
        v = values[i]
        if v is None:
            continue
        if isinstance(v, datetime.datetime):
            # 时间戳类型，只保留一个样例
            values = [v]
            break
        elif isinstance(v, datetime.date):
            # 日期类型，只保留一个样例
            values = [v]
            break
        elif isinstance(v, decimal.Decimal):
            values[i] = str(float(v))
        elif is_email(str(v)):
            # 邮箱属于隐私信息，丢弃整组
            values = []
            break
        elif 'http://' in str(v) or 'https://' in str(v):
            # URL 噪声，丢弃整组
            values = []
            break

    return [str(v) for v in values if v is not None and len(str(v)) > 0]

def extract_simple_json_from_qwen(qwen_result) -> dict:
    qwen_result=qwen_result.replace('\n', '')
    pattern = r"```json(.*?)```"

    # 使用re.DOTALL标志来使得点号(.)可以匹配包括换行符在内的任意字符
    sql_code_snippets = re.findall(pattern, qwen_result, re.DOTALL)
    data={}
    if len(sql_code_snippets) > 0:
        data = sql_code_snippets[-1].strip()
        try:
            data = eval(data)
        except:
            find = re.findall('错误信息\':\'(.*)\'', data)
            try:
                if len(find)>0:
                    find_out = find[0].replace('\'','"')
                    data=data.replace(find[0],find_out)
                    data = eval(data)
                else:

                    #re.findall('错误信息\':\'(.*)\'', data)[0].replace('\'', '"')
                    if "]}" in data:
                        data = data.replace(']}', '}]')
                        data = eval(data)
                    if 'false' in data or 'true' in data:
                        data = data.replace('false','False').replace('true','True')
                        data = eval(data)
                    else:
                        print("en error happened on eval")
                    data={}
            except:
                data={}
    return data

