"""Build a source index without copying case answers into the agent or repo.

Usage (PowerShell): python scripts/build-case-trace.py --cases <absolute-md> \
    --coverage docs/CASE-COVERAGE.md --output docs/CASE-TRACE.md
"""

import argparse
from collections import Counter
from pathlib import Path
import re


# Names are authoritative; document row order must never change classification.
CATEGORY_ALIASES = {
    "待处理订单商品修改": "ITEM_MOD",
    "已送达商品退货": "RETURN",
    "已送达商品换货": "EXCHANGE",
    "取消待处理订单": "CANCEL",
    "修改订单地址": "ORDER_ADDR",
    "修改默认地址": "DEFAULT_ADDR",
    "修改订单支付方式": "PAYMENT",
    "人工转接": "HUMAN",
    "无业务变更/查询/解释限制": "INFO",
}
ALIASES = tuple(CATEGORY_ALIASES.values())
BASELINE_COUNTS = (134, 176, 168)  # Current binding's public materials version.

TRACE = {
    "ITEM_MOD": ("IT-01/02,ST-02,CF-03", "GET order/product/item; POST item-modifications", "B3/B5/B7"),
    "RETURN": ("RT-01/02,ST-03,CF-01", "GET order/item/customer; POST returns", "B3/B6/B7"),
    "EXCHANGE": ("EX-01,ST-03,CF-01", "GET order/product/item/customer; POST exchanges", "B3/B5/B6"),
    "CANCEL": ("CA-01/02,RF-01,CF-01", "GET order/customer; POST cancellations", "B3/B4/B7"),
    "ORDER_ADDR": ("AD-01,ST-01,CF-01", "GET order; PUT order shipping-address", "B3/B4/B7"),
    "DEFAULT_ADDR": ("AD-01,CF-01", "GET customer; PUT default-shipping-address", "B3/B4/B7"),
    "PAYMENT": ("PY-01/02,ST-01,CF-01", "GET order/customer; PUT order payment-method", "B3/B4/B7"),
    "HUMAN": ("HO-01", "POST conversation transfers", "B7"),
    "INFO": ("ID-01/02,BN-01", "customer/order/catalog reads as permitted", "B1/B7"),
}

SIGNALS = (
    ("条件/回退", re.compile(r"如果|若|否则|优先|没有.*则|找不到.*就")),
    ("改口/追加", re.compile(r"改口|改主意|后来|随后|追加|再加|等等|先别|撤回|确认时|改变.*想法")),
    ("跨单", re.compile(r"所有.*订单|多个订单|两.*订单|三.*订单|每个订单")),
    ("支付/金额", re.compile(r"退款|差价|支付|礼品卡|金额|预算|美元")),
    ("身份/边界", re.compile(r"室友|配偶|邮箱|验证|找不到.*账户|人工|不能|不支持")),
)


def coverage_groups(path: Path) -> dict[int, list[str]]:
    groups: dict[str, list[int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        columns = [cell.strip() for cell in line.strip("|").split("|")]
        if len(columns) == 3 and columns[1].isdigit():
            name = columns[0]
            if name not in CATEGORY_ALIASES or name in groups:
                raise ValueError(f"Unknown or duplicate outcome category: {name}")
            if not re.fullmatch(r"\d+(?:,\d+)*", columns[2]):
                raise ValueError(f"Invalid case IDs for {name}")
            ids = [int(value) for value in columns[2].split(",")]
            if len(ids) != int(columns[1]) or len(set(ids)) != len(ids):
                raise ValueError("Coverage row count or duplicates do not match")
            groups[name] = ids
    if set(groups) != set(CATEGORY_ALIASES):
        raise ValueError("Expected nine outcome categories")
    per_case: dict[int, list[str]] = {case_id: [] for case_id in range(134)}
    for name, alias in CATEGORY_ALIASES.items():
        ids = groups[name]
        for case_id in ids:
            if case_id not in per_case:
                raise ValueError(f"Unexpected case ID {case_id}")
            per_case[case_id].append(alias)
    if any(not labels for labels in per_case.values()):
        raise ValueError("Some cases have no classified expected outcome")
    return per_case


def source_sections(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    heads = [(number, int(match.group(1))) for number, line in enumerate(lines, 1)
             if line.startswith("## ") and (match := re.search(r"ID (\d+)$", line))]
    if [case_id for _, case_id in heads] != list(range(134)):
        raise ValueError("Expected public case IDs 0..133 in order")
    for index, (start, case_id) in enumerate(heads):
        end = heads[index + 1][0] if index + 1 < len(heads) else len(lines) + 1
        section = lines[start - 1:end - 1]
        subheads = [offset for offset, line in enumerate(section) if line.startswith("### ")]
        if len(subheads) != 3:
            raise ValueError(f"Case {case_id} does not have three sections")
        need_line = next((start + offset for offset in range(subheads[0] + 1, subheads[1]) if section[offset].strip()), start + subheads[0])
        expected_lines = [start + offset for offset in range(subheads[1] + 1, subheads[2]) if section[offset].startswith("- ")]
        business_lines = [start + offset for offset in range(subheads[2] + 1, len(section)) if section[offset].startswith("- ")]
        if not expected_lines:
            raise ValueError(f"Case {case_id} has no expected outcome bullet")
        yield case_id, start, need_line, expected_lines, business_lines, "\n".join(section)


def build(cases: Path, coverage: Path) -> str:
    classified = coverage_groups(coverage)
    source_link = cases.resolve().as_posix()
    rows = []
    label_counts = Counter()
    business_count = 0
    for case_id, heading, need_line, expected_lines, business_lines, text in source_sections(cases):
        labels = classified[case_id]
        if len(expected_lines) != len(labels):
            raise ValueError(f"Case {case_id}: outcome bullets and categories disagree")
        label_counts.update(labels)
        business_count += len(business_lines)
        rules = sorted({rule for label in labels for rule in TRACE[label][0].split(",")})
        endpoints = "; ".join(dict.fromkeys(TRACE[label][1] for label in labels))
        batches = sorted({batch for label in labels for batch in TRACE[label][2].split("/")})
        flags = ", ".join(name for name, pattern in SIGNALS if pattern.search(text)) or "常规"
        business = ",".join(str(n) for n in business_lines) if business_lines else "—"
        rows.append(f"| {case_id} | [需求]({source_link}:{need_line}) / [期望]({source_link}:{expected_lines[0]}) | {','.join(labels)} | {business} | {','.join(rules)} | {endpoints} | {'/'.join(batches)} | {flags} |")
    if (len(rows), sum(label_counts.values()), business_count) != BASELINE_COUNTS:
        raise ValueError("Coverage totals changed")
    header = (
        "# M0 公开案例来源与能力追踪索引\n\n"
        "生成方式：`scripts/build-case-trace.py` 读取仓库外的公开案例说明和仓库内的分类表；**不复制案例原文或固定答案**。"
        "来源：[公开案例文件](" + source_link + ":1)、[分类口径](CASE-COVERAGE.md)、"
        "[规则台账](POLICY-REGISTER.md)、[API 清单](API-CONTRACT-MAP.md)。\n\n"
        f"本次索引 134 个 ID、176 个期望结果标签、{business_count} 个单列业务要求条目。"
        "表中规则、API 和测试批次是**候选映射**；来源位置、类别及条目计数已程序校验。"
        "客户需求段落可能包含多个条件和后续改口，`对话线索` 只用于优先审查，不能替代逐句原子化。"
        "业务要求以行号定位；全部案例的人工原子拆解、规则/API 及验收场景见 "
        "[CASE-REQUIREMENTS](CASE-REQUIREMENTS.md)。实际业务测试函数及结果仍待实施关联。\n\n"
        "| ID | 原文定位 | 期望类别 | 业务要求行号 | 候选规则 | 候选 API 链 | 拟测批次 | 对话线索 |\n"
        "|---:|---|---|---|---|---|---|---|\n"
    )
    footer = (
        "\n## 审查与完成边界\n\n"
        "1. 每个 ID 的需求、期望和业务要求都有来源位置；同一案例的多个期望结果没有合并成一个标签。\n"
        "2. 全案例需求、期望和业务要求的原子拆解见 [CASE-REQUIREMENTS](CASE-REQUIREMENTS.md)，"
        "本索引的类别候选不能替代其中的条件、偏好、顺序、反悔与金额说明。\n"
        "3. 原子验收场景已形成；随实施关联实际本地测试函数及运行结果，没有测试时标记待实现。\n"
        "4. 实际远程结果单独记录 Job 和范围；此表不是 134 项通过证明，也不授权改变 t1 绑定。\n"
        "5. 已人工复核的高风险需求见 [逐项决策审查](CASE-DECISION-REVIEWS.md)。\n"
    )
    return header + "\n".join(rows) + "\n" + footer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.cases, args.coverage)
    args.output.write_text(result, encoding="utf-8", newline="\n")
    print(f"Indexed 134 cases in {args.output}")


if __name__ == "__main__":
    main()
