# Unit tests for SEI model — cosine similarity, emitter database, EMA updates

import json
import os
import tempfile
import datetime

import numpy as np
from unittest.mock import MagicMock

import pytest

from ravensdr.sei_model import (
    SEIModel, EmitterRecord, cosine_similarity, l2_normalize,
    EMBEDDING_DIM, MATCH_THRESHOLD, EMA_ALPHA,
)


class TestCosineSimilarity:
    """Test cosine similarity computation."""

    def test_identical_vectors(self):
        v = np.random.randn(128).astype(np.float32)
        v = l2_normalize(v)
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = np.zeros(128, dtype=np.float32)
        a[0] = 1.0
        b = np.zeros(128, dtype=np.float32)
        b[1] = 1.0
        assert abs(cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self):
        v = np.random.randn(128).astype(np.float32)
        v = l2_normalize(v)
        assert abs(cosine_similarity(v, -v) + 1.0) < 1e-6

    def test_similar_vectors_above_threshold(self):
        v = np.random.randn(128).astype(np.float32)
        v = l2_normalize(v)
        # Very small perturbation to keep vectors similar
        noise = 0.02 * np.random.randn(128).astype(np.float32)
        w = l2_normalize(v + noise)
        sim = cosine_similarity(v, w)
        assert sim > 0.8  # should still be quite similar

    def test_zero_vector(self):
        v = np.ones(128, dtype=np.float32)
        z = np.zeros(128, dtype=np.float32)
        assert cosine_similarity(v, z) == 0.0


class TestL2Normalize:
    """Test L2 normalization."""

    def test_normalized_has_unit_norm(self):
        v = np.random.randn(128).astype(np.float32) * 5
        n = l2_normalize(v)
        assert abs(np.linalg.norm(n) - 1.0) < 1e-5

    def test_zero_vector_unchanged(self):
        v = np.zeros(128, dtype=np.float32)
        n = l2_normalize(v)
        assert np.all(n == 0)


class TestEmitterDatabase:
    """Test emitter database CRUD operations."""

    def _make_model(self, tmp_path):
        db_path = str(tmp_path / "test_emitter_db.json")
        return SEIModel(db_path=db_path)

    def test_enroll_emitter(self, tmp_path):
        model = self._make_model(tmp_path)
        embedding = l2_normalize(np.random.randn(EMBEDDING_DIM).astype(np.float32))
        eid = model._enroll_emitter(embedding, 121500000, "2026-03-17T00:00:00Z")
        assert eid == "EMITTER-001"
        assert model.get_emitter(eid) is not None
        assert model.get_emitter(eid)["observation_count"] == 1

    def test_enroll_sequential_ids(self, tmp_path):
        model = self._make_model(tmp_path)
        emb = l2_normalize(np.random.randn(EMBEDDING_DIM).astype(np.float32))
        e1 = model._enroll_emitter(emb, 100000000, "2026-03-17T00:00:00Z")
        e2 = model._enroll_emitter(emb, 200000000, "2026-03-17T00:00:01Z")
        assert e1 == "EMITTER-001"
        assert e2 == "EMITTER-002"

    def test_match_emitter_known(self, tmp_path):
        model = self._make_model(tmp_path)
        embedding = l2_normalize(np.random.randn(EMBEDDING_DIM).astype(np.float32))
        model._enroll_emitter(embedding, 100000000, "2026-03-17T00:00:00Z")

        # Query with same embedding should match
        result = model._match_emitter(embedding)
        assert result is not None
        eid, sim = result
        assert eid == "EMITTER-001"
        assert sim >= MATCH_THRESHOLD

    def test_match_emitter_unknown(self, tmp_path):
        model = self._make_model(tmp_path)
        emb1 = l2_normalize(np.random.randn(EMBEDDING_DIM).astype(np.float32))
        model._enroll_emitter(emb1, 100000000, "2026-03-17T00:00:00Z")

        # Query with very different embedding should NOT match
        emb2 = l2_normalize(np.random.randn(EMBEDDING_DIM).astype(np.float32))
        # Make it orthogonal
        emb2 = l2_normalize(emb2 - np.dot(emb2, emb1) * emb1)
        result = model._match_emitter(emb2)
        # Might match or not depending on random vectors — use truly different
        # For robustness, create a maximally different vector
        emb3 = -emb1
        result = model._match_emitter(emb3)
        assert result is None  # negative of the centroid should NOT match

    def test_update_emitter_ema(self, tmp_path):
        model = self._make_model(tmp_path)
        # Use a vector that points in one direction
        emb = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        emb[0] = 1.0  # unit vector along dim 0
        model._enroll_emitter(emb, 100000000, "2026-03-17T00:00:00Z")

        original = model._emitters["EMITTER-001"].embedding_centroid.copy()

        # Update with a vector pointing in a different direction
        new_emb = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        new_emb[1] = 1.0  # unit vector along dim 1
        model._update_emitter("EMITTER-001", new_emb, 100000000, "2026-03-17T01:00:00Z")

        updated = model._emitters["EMITTER-001"].embedding_centroid
        assert model._emitters["EMITTER-001"].observation_count == 2
        # Centroid should have shifted: dim 1 should now be non-zero
        assert updated[1] > 0.01
        # But still be L2-normalized
        assert abs(np.linalg.norm(updated) - 1.0) < 1e-5

    def test_label_emitter(self, tmp_path):
        model = self._make_model(tmp_path)
        emb = l2_normalize(np.random.randn(EMBEDDING_DIM).astype(np.float32))
        model._enroll_emitter(emb, 100000000, "2026-03-17T00:00:00Z")

        assert model.label_emitter("EMITTER-001", "My RTL-SDR")
        record = model.get_emitter("EMITTER-001")
        assert record["label"] == "My RTL-SDR"

    def test_label_nonexistent_returns_false(self, tmp_path):
        model = self._make_model(tmp_path)
        assert model.label_emitter("EMITTER-999", "test") is False

    def test_list_emitters_sorted(self, tmp_path):
        model = self._make_model(tmp_path)
        emb = l2_normalize(np.random.randn(EMBEDDING_DIM).astype(np.float32))
        model._enroll_emitter(emb, 100000000, "2026-03-17T01:00:00Z")
        model._enroll_emitter(emb, 200000000, "2026-03-17T03:00:00Z")
        model._enroll_emitter(emb, 300000000, "2026-03-17T02:00:00Z")

        result = model.list_emitters()
        assert result["total"] == 3
        # Should be sorted by last_seen descending
        timestamps = [e["last_seen"] for e in result["emitters"]]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_db_save_load_roundtrip(self, tmp_path):
        db_path = str(tmp_path / "roundtrip.json")
        model1 = SEIModel(db_path=db_path)
        emb = l2_normalize(np.random.randn(EMBEDDING_DIM).astype(np.float32))
        model1._enroll_emitter(emb, 100000000, "2026-03-17T00:00:00Z")
        model1.label_emitter("EMITTER-001", "Test Label")
        model1._save_db()

        # Load in new instance
        model2 = SEIModel(db_path=db_path)
        record = model2.get_emitter("EMITTER-001")
        assert record is not None
        assert record["label"] == "Test Label"
        assert record["observation_count"] == 1
        # Centroid should round-trip
        assert model2._emitters["EMITTER-001"].embedding_centroid is not None


class TestSEIIdentify:
    """Test end-to-end identification."""

    def test_identify_new_emitter(self, tmp_path):
        emitted = []
        model = SEIModel(
            emit_fn=lambda evt, data, **kw: emitted.append((evt, data)),
            db_path=str(tmp_path / "test.json"),
        )

        # Need enough samples and high enough "SNR"
        iq = 10.0 * np.exp(2j * np.pi * 50000 * np.arange(1024) / 2400000)

        result = model.identify(iq, frequency_hz=121500000,
                                 snr_db=20.0, duration_ms=200)

        assert result is not None
        assert result["event"] == "new_emitter"
        assert result["emitter_id"] == "EMITTER-001"
        # Check Socket.IO event emitted
        assert any(e[0] == "new_emitter" for e in emitted)

    def test_identify_re_identification(self, tmp_path):
        emitted = []
        model = SEIModel(
            emit_fn=lambda evt, data, **kw: emitted.append((evt, data)),
            db_path=str(tmp_path / "test.json"),
        )

        # Same signal twice — should enroll then re-identify
        iq = 10.0 * np.exp(2j * np.pi * 50000 * np.arange(1024) / 2400000)

        r1 = model.identify(iq, frequency_hz=121500000, snr_db=20.0, duration_ms=200)
        assert r1["event"] == "new_emitter"

        r2 = model.identify(iq, frequency_hz=121500000, snr_db=20.0, duration_ms=200)
        # CPU fallback should produce consistent embedding for same input
        assert r2 is not None
        assert r2["event"] == "re_identified"
        assert r2["emitter_id"] == "EMITTER-001"

    def test_identify_low_snr_rejected(self, tmp_path):
        model = SEIModel(db_path=str(tmp_path / "test.json"))
        iq = np.random.randn(1024) + 1j * np.random.randn(1024)
        result = model.identify(iq, snr_db=5.0, duration_ms=200)  # below MIN_SNR
        assert result is None

    def test_identify_short_duration_rejected(self, tmp_path):
        model = SEIModel(db_path=str(tmp_path / "test.json"))
        iq = np.random.randn(1024) + 1j * np.random.randn(1024)
        result = model.identify(iq, snr_db=20.0, duration_ms=50)  # below MIN_DURATION
        assert result is None

    def test_identify_too_few_samples_rejected(self, tmp_path):
        model = SEIModel(db_path=str(tmp_path / "test.json"))
        iq = np.array([1 + 0j, 2 + 0j])  # too short
        result = model.identify(iq, snr_db=20.0, duration_ms=200)
        assert result is None


class TestSEIStatus:
    """Test status reporting."""

    def test_initial_status(self, tmp_path):
        model = SEIModel(db_path=str(tmp_path / "test.json"))
        status = model.get_status()
        assert status["backend"] == "cpu"
        assert status["active"] is True
        assert status["emitter_count"] == 0
        assert status["embedding_dim"] == EMBEDDING_DIM
