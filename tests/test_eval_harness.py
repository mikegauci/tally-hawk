"""The eval harness scores saved predictions correctly (no API calls)."""

import json

from conftest import make_extracted

from evals.run_eval import main, render_report, summarize
from tallyhawk.extract import ExtractionResult, Usage
from tallyhawk.schema import InvoiceData
from tallyhawk.validation import low_confidence_fields, needs_review, validate_invoice


def write_prediction(pred_dir, case_id, invoice, confidence=0.98):
    extracted = make_extracted(invoice, confidence)
    issues = validate_invoice(invoice)
    low = low_confidence_fields(extracted)
    result = ExtractionResult(
        extracted=extracted,
        issues=issues,
        low_confidence_fields=low,
        needs_review=needs_review(issues, low),
        model="gpt-5.5",
        usage=Usage(input_tokens=1, output_tokens=1, cost_usd=0.01),
        latency_s=1.0,
    )
    (pred_dir / f"{case_id}.json").write_text(result.model_dump_json())


def test_perfect_predictions(tmp_path, gold_labels):
    labels = gold_labels[:10]
    for label in labels:
        write_prediction(tmp_path, label["case_id"], InvoiceData.model_validate(label["invoice"]))
    summary = summarize(labels, tmp_path)
    assert summary["document_accuracy"] == 1.0
    assert all(acc == 1.0 for acc in summary["field_accuracy"].values())
    assert summary["silent_error_rate"] == 0.0
    assert all(c["fp"] == 0 and c["fn"] == 0 for c in summary["issue_detection"].values())
    assert "# TallyHawk extraction eval" in render_report(summary, {"model": "m", "effort": "medium", "started": "t"})


def test_wrong_field_confident_is_a_silent_error(tmp_path, gold_labels):
    label = next(lb for lb in gold_labels if not lb["expected_issues"])
    gold = InvoiceData.model_validate(label["invoice"])
    write_prediction(tmp_path, label["case_id"], gold.model_copy(update={"invoice_number": "WRONG"}))
    summary = summarize([label], tmp_path)
    assert summary["field_accuracy"]["invoice_number"] == 0.0
    assert summary["document_accuracy"] == 0.0
    assert summary["silent_error_rate"] == 1.0


def test_failed_cases_are_reported(tmp_path, gold_labels):
    label = gold_labels[0]
    (tmp_path / f"{label['case_id']}.json").write_text('{"error": "APIConnectionError: boom"}')
    summary = summarize([label], tmp_path)
    assert summary["n_scored"] == 0 and summary["failures"][0]["case_id"] == label["case_id"]


def test_rescore_splits_sets_and_prices_old_runs(tmp_path, gold_labels, monkeypatch):
    pred_dir = tmp_path / "predictions"
    pred_dir.mkdir()
    for label in gold_labels:
        gold = InvoiceData.model_validate(label["invoice"])
        if label["case_id"] == "inv_051":  # a hard case read wrong, with high confidence
            gold = gold.model_copy(update={"invoice_number": "WRONG"})
        write_prediction(pred_dir, label["case_id"], gold)
    (tmp_path / "summary.json").write_text(json.dumps({"meta": {"model": "m", "effort": "medium", "started": "t"}}))
    monkeypatch.setenv("TALLYHAWK_PRICE_INPUT_PER_MTOK", "5")
    monkeypatch.setenv("TALLYHAWK_PRICE_OUTPUT_PER_MTOK", "30")

    summary = main(["--rescore", str(tmp_path)])

    assert list(summary["sets"]) == ["standard", "hard"]
    assert summary["sets"]["standard"]["document_accuracy"] == 1.0
    assert summary["sets"]["hard"]["silent_error_rate"] > 0
    assert summary["by_tag"]["scanned_rotated"]["n"] == 2
    assert summary["cost_usd_per_invoice"] == round((5 + 30) / 1e6, 5)  # 1 token in, 1 out, at current prices
    assert summary["confidence_calibration"]["mean_conf_wrong"] == 0.98
    report = (tmp_path / "report.md").read_text()
    assert "## Standard vs hard invoices" in report and "| inv_051 | hard | invoice_number" in report
