"""Unit tests for src.artifacts.ArtifactStore."""

from __future__ import annotations

import json
import os
import shutil


class TestArtifactStore:
    def test_creates_directory_structure(self, sample_pdf, tmp_path):
        os.chdir(tmp_path)
        from src.artifacts import ArtifactStore

        store = ArtifactStore(sample_pdf)
        assert os.path.isdir(store.root)
        assert os.path.isdir(store.pages_dir)
        assert os.path.isdir(store.slides_dir)
        assert store.root.startswith("runs/run-")
        shutil.rmtree("runs")

    def test_dry_run_prefix(self, sample_pdf, tmp_path):
        os.chdir(tmp_path)
        from src.artifacts import ArtifactStore

        store = ArtifactStore(sample_pdf, dry_run=True)
        assert store.root.startswith("runs/dry-run-")
        shutil.rmtree("runs")

    def test_replay_prefix(self, sample_pdf, tmp_path):
        os.chdir(tmp_path)
        from src.artifacts import ArtifactStore

        store = ArtifactStore(sample_pdf, replay_of="runs/run-test-20260101-000000")
        assert store.root.startswith("runs/replay-")
        shutil.rmtree("runs")

    def test_save_page_images(self, sample_pdf, tmp_path):
        os.chdir(tmp_path)
        from src.artifacts import ArtifactStore
        from src.pdf_preprocessor import pdf_to_images

        store = ArtifactStore(sample_pdf)
        pages = pdf_to_images(sample_pdf, dpi=72)
        store.save_page_images(pages)

        assert os.path.isfile(os.path.join(store.pages_dir, "page_000.png"))
        assert os.path.isfile(os.path.join(store.pages_dir, "page_001.png"))
        shutil.rmtree("runs")

    def test_save_run_params(self, sample_pdf, tmp_path):
        os.chdir(tmp_path)
        from src.artifacts import ArtifactStore

        store = ArtifactStore(sample_pdf)
        store.save_run_params({"dpi": 288, "model": "gpt-5.4"})

        path = os.path.join(store.root, "run_params.json")
        assert os.path.isfile(path)
        with open(path) as f:
            data = json.load(f)
        assert data["dpi"] == 288
        shutil.rmtree("runs")

    def test_save_reasoning(self, sample_pdf, tmp_path):
        os.chdir(tmp_path)
        from src.artifacts import ArtifactStore

        store = ArtifactStore(sample_pdf)
        store.save_reasoning("This is the model's thinking process.", batch_idx=0)

        path = os.path.join(store.root, "reasoning_0.txt")
        assert os.path.isfile(path)
        with open(path) as f:
            assert "thinking process" in f.read()
        shutil.rmtree("runs")

    def test_save_reasoning_skips_empty(self, sample_pdf, tmp_path):
        os.chdir(tmp_path)
        from src.artifacts import ArtifactStore

        store = ArtifactStore(sample_pdf)
        store.save_reasoning("", batch_idx=0)

        assert not os.path.isfile(os.path.join(store.root, "reasoning_0.txt"))
        shutil.rmtree("runs")

    def test_save_content_text(self, sample_pdf, tmp_path):
        os.chdir(tmp_path)
        from src.artifacts import ArtifactStore

        store = ArtifactStore(sample_pdf)
        store.save_content_text("Some content output", batch_idx=0)

        path = os.path.join(store.root, "content_0.txt")
        assert os.path.isfile(path)
        shutil.rmtree("runs")

    def test_save_slide_xmls(self, sample_pdf, tmp_path):
        os.chdir(tmp_path)
        from src.artifacts import ArtifactStore

        store = ArtifactStore(sample_pdf)
        store.save_slide_xmls({0: "<p:sld>slide0</p:sld>", 1: "<p:sld>slide1</p:sld>"})

        assert os.path.isfile(os.path.join(store.slides_dir, "slide_000.xml"))
        assert os.path.isfile(os.path.join(store.slides_dir, "slide_001.xml"))
        shutil.rmtree("runs")

    def test_api_response_indexing(self, sample_pdf, tmp_path):
        os.chdir(tmp_path)
        from src.artifacts import ArtifactStore

        store = ArtifactStore(sample_pdf)
        store.set_batch_count(2)
        store.save_api_response({"batch": 0}, batch_idx=0)
        store.save_api_response({"batch": 1}, batch_idx=1)

        assert os.path.isfile(os.path.join(store.root, "api_response_0.json"))
        assert os.path.isfile(os.path.join(store.root, "api_response_1.json"))
        shutil.rmtree("runs")

    def test_save_metadata(self, sample_pdf, tmp_path):
        os.chdir(tmp_path)
        from src.artifacts import ArtifactStore

        store = ArtifactStore(sample_pdf)
        store.save_metadata({"pages": 2, "dpi": 288})

        path = os.path.join(store.root, "metadata.json")
        assert os.path.isfile(path)
        with open(path) as f:
            data = json.load(f)
        assert data["pages"] == 2
        shutil.rmtree("runs")

    def test_copy_input(self, sample_pdf, tmp_path):
        os.chdir(tmp_path)
        from src.artifacts import ArtifactStore

        store = ArtifactStore(sample_pdf)
        store.copy_input(sample_pdf)

        copied = os.path.join(store.root, os.path.basename(sample_pdf))
        assert os.path.isfile(copied)
        shutil.rmtree("runs")
