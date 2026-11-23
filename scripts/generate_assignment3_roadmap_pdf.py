#!/usr/bin/env python3
"""
Generate the Assignment 03 (RAGOps) Master Roadmap, Architecture Breakdown,
and Partner Division Guide PDF.
Follows professional academic formatting standards (Monochrome/Charcoal, Times-Roman, NumberedCanvas).
"""

import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages):
        self.saveState()
        self.setFont("Times-Roman", 9)
        self.setFillColor(colors.HexColor("#444444"))
        
        # Running header on pages > 1
        if self._pageNumber > 1:
            self.drawString(54, 11 * inch - 36, "RAHBAR RAGOps: Assignment 03 Master Roadmap & Work Allocation")
            self.setStrokeColor(colors.HexColor("#CCCCCC"))
            self.setLineWidth(0.5)
            self.line(54, 11 * inch - 40, 8.5 * inch - 54, 11 * inch - 40)
            
        # Running footer on all pages
        page_str = f"Page {self._pageNumber} of {total_pages}"
        self.drawRightString(8.5 * inch - 54, 36, page_str)
        self.drawString(54, 36, "FAST NUCES | Software Construction & Development (CS4032) — Assignment 03")
        self.setStrokeColor(colors.HexColor("#CCCCCC"))
        self.setLineWidth(0.5)
        self.line(54, 46, 8.5 * inch - 54, 46)
        
        self.restoreState()

def build_pdf(filename="docs/Assignment_03_RAGOps_Master_Roadmap.pdf"):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Times-Bold',
        fontSize=18,
        leading=22,
        alignment=1, # Center
        spaceAfter=5,
        textColor=colors.HexColor("#111111")
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Times-Italic',
        fontSize=11,
        leading=15,
        alignment=1, # Center
        spaceAfter=12,
        textColor=colors.HexColor("#333333")
    )

    meta_style = ParagraphStyle(
        'MetaBox',
        parent=styles['Normal'],
        fontName='Times-Roman',
        fontSize=9.5,
        leading=13.5,
        alignment=1,
        spaceAfter=12,
        textColor=colors.HexColor("#222222")
    )

    h1_style = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Normal'],
        fontName='Times-Bold',
        fontSize=13,
        leading=17,
        spaceBefore=12,
        spaceAfter=5,
        keepWithNext=True,
        textColor=colors.HexColor("#111111")
    )

    h2_style = ParagraphStyle(
        'Heading2_Custom',
        parent=styles['Normal'],
        fontName='Times-Bold',
        fontSize=11,
        leading=14,
        spaceBefore=8,
        spaceAfter=3,
        keepWithNext=True,
        textColor=colors.HexColor("#222222")
    )

    body_style = ParagraphStyle(
        'Body_Custom',
        parent=styles['Normal'],
        fontName='Times-Roman',
        fontSize=9,
        leading=13,
        spaceAfter=4,
        textColor=colors.HexColor("#222222")
    )

    bullet_style = ParagraphStyle(
        'Bullet_Custom',
        parent=styles['Normal'],
        fontName='Times-Roman',
        fontSize=9,
        leading=13,
        leftIndent=14,
        firstLineIndent=-9,
        spaceAfter=3,
        textColor=colors.HexColor("#222222")
    )

    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='Times-Bold',
        fontSize=8.5,
        leading=11,
        alignment=0,
        textColor=colors.white
    )

    table_cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Times-Roman',
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor("#222222")
    )

    table_cell_bold = ParagraphStyle(
        'TableCellBold',
        parent=styles['Normal'],
        fontName='Times-Bold',
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor("#111111")
    )

    story = []

    # Title & Metadata
    story.append(Paragraph("RAHBAR RAGOps: Assignment 03 Master Blueprint", title_style))
    story.append(Paragraph("Operationalizing RAGOps (Xu et al., 2026) on Kubernetes — Architecture Breakdown, Phased Roadmap & Work Division", subtitle_style))
    
    meta_text = (
        "<b>Course:</b> Software Construction & Development (CS4032), Fall 2026 | <b>Total Marks:</b> 185<br/>"
        "<b>Team Members:</b> Zubair Ilyas & Salman Asad | <b>Base System:</b> RAHBAR (Assignment 02)<br/>"
        "<b>Foundational Paper:</b> Xu et al., <i>'RAGOps: Operating and Managing Retrieval-Augmented Generation Pipelines'</i> (2026)"
    )
    story.append(Paragraph(meta_text, meta_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#222222"), spaceAfter=10))

    # SECTION 1: CONCEPTUAL ALIGNMENT
    story.append(Paragraph("1. Conceptual Alignment with the RAGOps Research Paper", h1_style))
    story.append(Paragraph(
        "Assignment 03 transitions RAHBAR from a static Retrieval-Augmented Generation pipeline into a dynamic, "
        "production-grade <b>RAGOps ecosystem</b> as conceptualized by Xu et al. (2026). While standard LLMOps focuses "
        "almost exclusively on model fine-tuning and prompt engineering, RAGOps addresses the reality that external "
        "data sources evolve rapidly, drift over time, and introduce poisoning risks.", body_style
    ))
    
    story.append(Paragraph("<b>The Dual Intertwined Lifecycles (Figure 3):</b>", h2_style))
    story.append(Paragraph(
        "Our system explicitly decouples the <b>Query Processing Lifecycle</b> (online, serving low-latency user requests) "
        "from the <b>Data Management Lifecycle</b> (offline batch jobs verifying, updating, and evaluating corpus integrity). "
        "The vector store is strictly read-only for the API deployment and is only written to by the Kubernetes Ingestion Job.",
        bullet_style
    ))
    
    story.append(Paragraph("<b>Three-Level Testing Platform (Table 1):</b>", h2_style))
    story.append(Paragraph(
        "Following Table 1 of the paper, testing is stratified into three distinct abstraction boundaries: "
        "(1) <i>Module Level</i>: Evaluating embedding quality (paraphrase vs. unrelated cosine separation, generation latency, determinism). "
        "(2) <i>Component Level</i>: Evaluating retrieval accuracy (Recall@k, MRR, nDCG@5, noise resilience). "
        "(3) <i>End-to-End System Level</i>: Evaluating generated responses (Faithfulness/Context Adherence, Abstention Correctness, Citation Validity, P50/P95 latencies).",
        bullet_style
    ))

    story.append(Paragraph("<b>The Five System Qualities (Table 2):</b>", h2_style))
    story.append(Paragraph(
        "The architecture establishes concrete operational metrics for: "
        "<b>Adaptability</b> (handling changing document schemas and versions), "
        "<b>Monitorability</b> (detecting accuracy degradation and data drift), "
        "<b>Observability</b> (full query tracing and prompt-injection detection), "
        "<b>Traceability</b> (complete chunk-to-source provenance and version tags), and "
        "<b>Reliability</b> (zero-downtime rolling updates, resource limits, rollback guarantees).",
        bullet_style
    ))
    story.append(Spacer(1, 6))

    # SECTION 2: WORK BREAKDOWN STRUCTURE
    story.append(Paragraph("2. Complete Technical Work Breakdown Structure (Parts A to G)", h1_style))
    story.append(Paragraph(
        "The following table decomposes the 185-mark assignment into discrete, testable technical deliverables:", body_style
    ))

    wbs_data = [
        [Paragraph("<b>Part & Focus</b>", table_header_style), Paragraph("<b>Core Technical Requirements & Mechanisms</b>", table_header_style), Paragraph("<b>Primary Artifacts & Files</b>", table_header_style)],
        
        [Paragraph("<b>Part A<br/>Data Management:<br/>Verify & Update</b><br/>(Paper 4.2.1–4.2.4)", table_cell_bold),
         Paragraph("• <b>4 Pre-chunking Verification Checks</b>: Quality (empty/garbled), Completeness (required metadata, truncation), Recency (detect newer versions), Uniqueness (exact hash + near-duplicate cosine similarity).<br/>"
                   "• <b>Quarantine Mechanism</b>: Failed docs moved to quarantine folder; outputs verification JSON report per run.<br/>"
                   "• <b>Incremental Ingestion</b>: Re-running on unchanged corpus embeds 0 chunks; updated doc replaces only its own chunks; deleted doc leaves 0 orphan chunks; superseded versions archived with metadata tag (rollback enabled).<br/>"
                   "• <b>Batch B Synthesis</b>: 10 planted-defect documents (2 exact duplicates, 1 near-dup, 1 corrupt, 1 missing metadata, 1 newer version, 1 prompt injection).", table_cell_style),
         Paragraph("• indexer/pipeline/verify.py<br/>• indexer/pipeline/incremental.py<br/>• corpus/batch_b/<br/>• eval/results/verification_report.json", table_cell_style)],

        [Paragraph("<b>Part B<br/>Offline Testing at<br/>Three Levels</b><br/>(Paper 4.2.5, Table 1)", table_cell_bold),
         Paragraph("• <b>Golden Set Expansion</b>: &ge; 25 questions in eval/golden.jsonl (&ge; 15 answerable, &ge; 5 unanswerable, &ge; 5 hard; labeled human vs synthetic; &ge; 8 reviewed by hand).<br/>"
                   "• <b>Module Level</b>: Mean cosine similarity for 15 paraphrase vs 15 unrelated pairs; embedding time per chunk; determinism diff.<br/>"
                   "• <b>Component Level</b>: Recall@3, Recall@5, MRR, nDCG@5; noise test (typos or 3 irrelevant docs).<br/>"
                   "• <b>End-to-End Level</b>: Faithfulness (LLM-as-judge calibrated against 8 human labels), Abstention correctness, Citation validity, P50 & P95 latencies.<br/>"
                   "• <b>Stochasticity</b>: Fixed-seed run twice reporting metric deltas. Single unified runner script.", table_cell_style),
         Paragraph("• eval/golden.jsonl<br/>• eval/test_three_levels.py<br/>• eval/results/three_level_eval.json", table_cell_style)],

        [Paragraph("<b>Part C<br/>Change Experiment &<br/>Release Gate</b><br/>(Paper 4.1d, 4.2.5, 4.2.6)", table_cell_bold),
         Paragraph("• <b>One Pipeline Change</b>: Formally evaluate 1 change (e.g. chunk size 500 &rarr; 800 or Top-K 5 &rarr; 3). Run Part B suite on baseline vs candidate.<br/>"
                   "• <b>Automated Release Gate</b>: Thresholds defined in config (Recall@5 drop &le; 2%, Faithfulness &ge; threshold, P95 latency &le; threshold, Abstention no lower). Script outputs Pass/Fail exit code (0/1).<br/>"
                   "• Demonstrate 1 candidate that fails and 1 that passes.", table_cell_style),
         Paragraph("• eval/release_gate.py<br/>• k8s/base/gate-thresholds.yaml<br/>• eval/results/candidate_comparison.json", table_cell_style)],

        [Paragraph("<b>Part D<br/>Observability &<br/>Traceability</b><br/>(Paper 3.2.3, 5.1, Table 2)", table_cell_bold),
         Paragraph("• <b>Rich JSON Trace Record</b>: Every query logs trace_id, timestamp, query rewrite, model & collection versions, retrieved chunk IDs with doc IDs & scores, filters applied, prompt hash, model params, response, citations, guardrail actions, per-stage latency, cache status.<br/>"
                   "• <b>Trace CLI Tool</b>: Command taking trace_id and printing exact reconstructed context and prompt.<br/>"
                   "• <b>Metrics Summary</b>: Script reporting top-1 similarity distribution, abstention rate, cache hit rate, P95 stage latency, injection attempts flagged.<br/>"
                   "• <b>Guardrail Logging</b>: Trace logs injection defense actions (Batch B test).<br/>"
                   "• <b>Trace Root Cause</b>: 5-line diagnosis of 1 failed query using only trace data.", table_cell_style),
         Paragraph("• api/app/tracing.py<br/>• traces/inspect.py<br/>• traces/metrics_summary.py<br/>• traces/live_traces.jsonl", table_cell_style)],

        [Paragraph("<b>Part E<br/>Drift & Coverage<br/>Checking</b><br/>(Paper 4.2.7)", table_cell_bold),
         Paragraph("• <b>Live Query Log</b>: &ge; 40 queries (28 in-domain, 12 out-of-domain).<br/>"
                   "• <b>Query Coverage Checking</b>: Embedding similarity against golden set. Report % reaching threshold (flag gap if &lt; 85%). Group uncovered queries into topics.<br/>"
                   "• <b>Data Drift</b>: Ingest Batch B, re-run Part B suite, report metric shifts.<br/>"
                   "• <b>Close the Gap</b>: Add 6 new golden questions from uncovered topics, re-run, show coverage rise. Script exits non-zero if coverage &lt; threshold.", table_cell_style),
         Paragraph("• eval/live_queries.jsonl<br/>• eval/check_coverage.py<br/>• eval/results/coverage_report.json", table_cell_style)],

        [Paragraph("<b>Part F<br/>Kubernetes Deployment &<br/>Controlled Release</b><br/>(Paper 4.1e,f, 5.1)", table_cell_bold),
         Paragraph("• <b>Persistent State</b>: PVCs for data lake, quarantine, archives, and traces.<br/>"
                   "• <b>Kubernetes Jobs</b>: Ingestion Job + CronJob (only vector store writer). Evaluation Job (k8s/eval-job.yaml) running Part B suite and enforcing release gate.<br/>"
                   "• <b>ConfigMap Gating</b>: Changing gate threshold in ConfigMap changes pass/fail outcome without image rebuild.<br/>"
                   "• <b>Controlled Release & Rollback</b>: Candidate deployment with separate service/collection. Rolling update (maxUnavailable: 0) on pass. Show stopped bad release and rollback via 'kubectl rollout undo' (trace proves previous model restored).<br/>"
                   "• <b>Cluster Observability & Resources</b>: JSON logs to stdout & volume; Prometheus /metrics; requests/limits justified by live kubectl top.", table_cell_style),
         Paragraph("• k8s/base/pvc-datalake.yaml<br/>• k8s/base/eval-job.yaml<br/>• k8s/base/candidate-deployment.yaml<br/>• k8s/base/gate-configmap.yaml", table_cell_style)],

        [Paragraph("<b>Part G<br/>Report & Screenshots<br/>Appendix</b><br/>(8 Pages Max)", table_cell_bold),
         Paragraph("• Section 1: Table mapping Figure 3 stages to our files.<br/>"
                   "• Section 2: Table for Table 2 qualities (Adaptability, Monitorability, Observability, Traceability, Reliability).<br/>"
                   "• Section 3: Result tables from Parts A to F and Part C release decision.<br/>"
                   "• Section 4: Short answers (a to f).<br/>"
                   "• Section 5: Contribution table + AI statement.<br/>"
                   "• Appendix: Complete, uncropped terminal screenshots for Parts A–F.", table_cell_style),
         Paragraph("• docs/Assignment_03_Report.pdf<br/>• docs/evidence/screenshots_a_to_f/", table_cell_style)]
    ]

    t_wbs = Table(wbs_data, colWidths=[1.5 * inch, 4.0 * inch, 1.5 * inch])
    t_wbs.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#222222")),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('BACKGROUND', (0,1), (0,-1), colors.HexColor("#F9F9F9")),
    ]))
    story.append(t_wbs)
    story.append(Spacer(1, 10))

    # SECTION 3: PARTNER DIVISION OF RESPONSIBILITY
    story.append(PageBreak())
    story.append(Paragraph("3. Partner Division of Labor: Zubair Ilyas vs. Salman Asad", h1_style))
    story.append(Paragraph(
        "To guarantee balanced contributions ($50\\% / 50\\%$) in git history, PR approvals, and viva defense, "
        "the architecture is partitioned cleanly into two major ownership domains with explicit integration contracts:", body_style
    ))
    story.append(Spacer(1, 4))

    division_data = [
        [Paragraph("<b>Dimension</b>", table_header_style), Paragraph("<b>Partner A: Zubair Ilyas (Data & Eval Lead)</b>", table_header_style), Paragraph("<b>Partner B: Salman Asad (Ops & Tracing Lead)</b>", table_header_style)],
        
        [Paragraph("<b>Primary Domain</b>", table_cell_bold),
         Paragraph("<b>Data Management & Evaluation Engineering</b><br/>Owns corpus verification, test suites, drift, and offline statistical metrics.", table_cell_style),
         Paragraph("<b>Kubernetes DevOps & Tracing Engineering</b><br/>Owns cluster orchestration, Jobs, controlled releases, observability, and tracing.", table_cell_style)],

        [Paragraph("<b>Part A (Data Mgmt)</b>", table_cell_bold),
         Paragraph("• Lead: Builds indexer/pipeline/verify.py (Quality, Completeness, Recency, Uniqueness checks).<br/>"
                   "• Generates Batch B planted-defect documents.<br/>"
                   "• Generates verification JSON reports.", table_cell_style),
         Paragraph("• Support: Builds indexer/pipeline/incremental.py (hash comparison, chunk replacement, orphan cleanup).<br/>"
                   "• Configures persistent data lake and quarantine PVC mounts in K8s.", table_cell_style)],

        [Paragraph("<b>Part B (3-Level Eval)</b>", table_cell_bold),
         Paragraph("• Lead: Expands eval/golden.jsonl (&ge; 25 questions).<br/>"
                   "• Builds Level 2 (Retrieval: Recall, MRR, nDCG, noise) and Level 3 (Faithfulness, LLM judge vs 8 hand labels).<br/>"
                   "• Analyzes stochasticity and metric deltas.", table_cell_style),
         Paragraph("• Support: Builds Level 1 (Embedding module: paraphrase vs unrelated similarity gap, embed latency, determinism).<br/>"
                   "• Packages the unified test runner and latency profiling timers.", table_cell_style)],

        [Paragraph("<b>Part C (Release Gate)</b>", table_cell_bold),
         Paragraph("• Lead: Defines candidate pipeline change (chunking or Top-K).<br/>"
                   "• Builds eval/release_gate.py comparing candidate vs baseline metrics.", table_cell_style),
         Paragraph("• Support: Parameterizes gate thresholds into Kubernetes ConfigMap.<br/>"
                   "• Validates gate pass/fail exit codes for CI/CD.", table_cell_style)],

        [Paragraph("<b>Part D (Tracing & Obs)</b>", table_cell_bold),
         Paragraph("• Support: Connects prompt-injection guardrail into trace output.<br/>"
                   "• Performs the trace-only root cause diagnosis (Part D5).", table_cell_style),
         Paragraph("• Lead: Builds FastAPI JSON-lines tracing middleware (api/app/tracing.py).<br/>"
                   "• Builds CLI trace inspection tool (traces/inspect.py) and windowed metrics aggregator.", table_cell_style)],

        [Paragraph("<b>Part E (Drift & Coverage)</b>", table_cell_bold),
         Paragraph("• Lead: Generates 40 live queries log.<br/>"
                   "• Builds eval/check_coverage.py (embedding similarity gating, topic grouping, and closing the gap).<br/>"
                   "• Evaluates Batch B data drift.", table_cell_style),
         Paragraph("• Support: Integrates coverage check into evaluation Job.<br/>"
                   "• Validates non-zero exit code behavior under low coverage.", table_cell_style)],

        [Paragraph("<b>Part F (Kubernetes)</b>", table_cell_bold),
         Paragraph("• Support: Tests and validates the Ingestion Job and Evaluation Job outputs inside the cluster.", table_cell_style),
         Paragraph("• Lead: Authors all K8s manifests (PVCs, Ingestion Job, eval-job.yaml, candidate deployment).<br/>"
                   "• Executes controlled rollout, rollout undo, and resource measurements (kubectl top).", table_cell_style)],

        [Paragraph("<b>Part G (Report & Demo)</b>", table_cell_bold),
         Paragraph("• Co-author: Sections 1 (Fig 3 mapping), 3 (Eval results), 4 (Short answers a, b, d).<br/>"
                   "• Captures terminal screenshots for Parts A, B, E.", table_cell_style),
         Paragraph("• Co-author: Sections 2 (Table 2 qualities), 4 (Short answers c, e, f), 5 (Contribution).<br/>"
                   "• Captures terminal screenshots for Parts C, D, F.", table_cell_style)]
    ]

    t_div = Table(division_data, colWidths=[1.3 * inch, 2.85 * inch, 2.85 * inch])
    t_div.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#222222")),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('BACKGROUND', (0,1), (0,-1), colors.HexColor("#F5F5F5")),
    ]))
    story.append(t_div)
    story.append(Spacer(1, 10))

    # SECTION 4: STEP-BY-STEP PHASED ROADMAP
    story.append(Paragraph("4. Step-by-Step Phased Implementation Roadmap", h1_style))
    story.append(Paragraph(
        "To avoid merge bottlenecks, development proceeds across 7 sequential phases where each phase produces "
        "committed test artifacts and verified outputs:", body_style
    ))

    roadmap_steps = [
        ("Phase 1: Verification Engine & Batch B Synthesis (Part A)",
         "Build verify.py implementing Quality (text > 50 chars), Completeness (required metadata present), Recency (date/version parsing), and Uniqueness (SHA-256 exact hash + embedding similarity threshold 0.95 for near-duplicates). Build quarantine router. Synthesize 10-document Batch B with planted defects. Implement incremental chunk hasher in incremental.py (re-running unchanged corpus embeds 0 chunks)."),
        
        ("Phase 2: Three-Level Offline Evaluation Suite (Part B)",
         "Expand golden set to 25 questions in eval/golden.jsonl with human/synthetic tags. Implement Level 1 module tests (paraphrase vs unrelated cosine gap, embed time, determinism). Implement Level 2 component tests (Recall@3/5, MRR, nDCG@5, noise test with typos). Implement Level 3 end-to-end tests (Faithfulness LLM judge calibrated against 8 human labels, abstention correctness, citation validity, P50/P95 latencies). Fix random seeds, execute twice, and record delta."),

        ("Phase 3: Observability Middleware & Trace Tooling (Part D)",
         "Implement FastAPI tracing middleware emitting rich JSON-lines to stdout and a shared trace volume. Implement traces/inspect.py CLI tool that reconstructs exact prompt and context from a trace ID. Implement windowed metrics aggregator. Connect prompt injection guardrail action to trace output. Document trace-only root cause analysis."),

        ("Phase 4: Candidate Experiment & Release Gate (Part C)",
         "Define baseline vs candidate change (e.g. chunk size 500/100 vs 800/150). Run Part B suite on both. Implement eval/release_gate.py that checks metric drops against configurable thresholds. Prove that candidate 1 fails and candidate 2 passes, exiting with non-zero or zero status."),

        ("Phase 5: Drift & Coverage Checking Engine (Part E)",
         "Create 40 live queries (28 in-domain, 12 out-of-domain). Implement check_coverage.py comparing live queries to golden set embeddings (flag gap if < 85%). Ingest Batch B, re-run Part B suite to measure data drift. Add 6 new golden questions to close the gap and prove coverage increase."),

        ("Phase 6: Kubernetes Orchestration & Controlled Release (Part F)",
         "Provision PVCs for data lake, quarantine, and archive. Package Ingestion Job and Evaluation Job (eval-job.yaml) running in cluster. Parameterize gate thresholds into a ConfigMap. Deploy candidate service and demonstrate controlled rolling update (maxUnavailable: 0) and rollback via 'kubectl rollout undo' (trace proves previous model restored). Record live kubectl top resource usage."),

        ("Phase 7: Report Authoring & Screenshots Appendix (Part G)",
         "Compile the formal 8-page report matching Figure 3 and Table 2. Draft the 6 technical short answers with exact file and line references. Collect and label all required uncropped terminal screenshots into the appendix.")
    ]

    for title, desc in roadmap_steps:
        story.append(Paragraph(f"<b>{title}</b>", h2_style))
        story.append(Paragraph(desc, bullet_style))
        story.append(Spacer(1, 2))

    story.append(Spacer(1, 8))

    # SECTION 5: IS ANYTHING REQUIRED FROM THE USER?
    story.append(Paragraph("5. Requirements & Environmental Readiness Check", h1_style))
    story.append(Paragraph(
        "<b>Are any external credentials, datasets, or inputs required from the user?</b><br/>"
        "<b>No.</b> Everything required to execute Assignment 03 is already fully in place within your local environment:", body_style
    ))
    
    req_items = [
        "<b>Corpus & Ground Truth:</b> Your 279-page university corpus from Assignment 02 is intact and ready. Batch B will be synthesized programmatically to plant exact known defects.",
        "<b>Vector Store & LLM:</b> ChromaDB (persisted on disk) and local Ollama (with llama3.2:1b and nomic-embed-text) are installed and fully functional.",
        "<b>Kubernetes Environment:</b> Minikube and Docker are installed locally on your machine, ready for Part F Job and StatefulSet deployments.",
        "<b>Python Libraries:</b> PyPDF, PyMuPDF (fitz), ReportLab, ChromaDB, FastAPI, Pydantic, and Uvicorn are available.",
        "<b>Git Repository:</b> Your GitHub repository (Zubairilyas1/Rahbar-Starter) is clean, synced, and adheres to GitFlow with full branch protection."
    ]
    for r in req_items:
        story.append(Paragraph(f"• {r}", bullet_style))
        
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#666666"), spaceAfter=8))
    story.append(Paragraph(
        "<b>Conclusion:</b> We are 100% self-contained and ready to begin implementation immediately. "
        "Upon your signal, we will launch Phase 1 (Data Verification Engine & Batch B Synthesis).", meta_style
    ))

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Successfully generated {filename}!")

if __name__ == "__main__":
    build_pdf()
