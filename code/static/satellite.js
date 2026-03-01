// Satellite panel — APT pass schedule, countdown, recording status, decoded images

(function () {
    "use strict";

    function SatellitePanel(socket) {
        this.socket = socket;
        this.passes = [];
        this.countdownInterval = null;
        this.recordingInterval = null;
        this.recordingStart = null;
        this.recordingDuration = 0;

        this._bindEvents();
        this._fetchPasses();
        this._fetchLatestImage();
    }

    SatellitePanel.prototype._bindEvents = function () {
        var self = this;

        this.socket.on("satellite_pass_upcoming", function (data) {
            self._onPassUpcoming(data);
        });

        this.socket.on("apt_image_ready", function (data) {
            self._onImageReady(data);
        });

        this.socket.on("status", function (data) {
            self._updateRecordingStatus(data);
        });
    };

    SatellitePanel.prototype._fetchPasses = function () {
        var self = this;
        fetch("/api/satellite/passes")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (Array.isArray(data)) {
                    self.passes = data;
                    self._renderPasses();
                    self._startCountdown();
                }
            })
            .catch(function () {
                // Satellite API may not be available
            });
    };

    SatellitePanel.prototype._fetchLatestImage = function () {
        var self = this;
        fetch("/api/satellite/latest-image")
            .then(function (r) {
                if (r.ok) return r.json();
                return null;
            })
            .then(function (data) {
                if (data && data.url) {
                    self._displayImage(data);
                }
            })
            .catch(function () {});
    };

    SatellitePanel.prototype._renderPasses = function () {
        var list = document.getElementById("sat-pass-list");
        if (!list) return;

        list.innerHTML = "";
        var upcoming = this.passes.slice(0, 5);

        if (upcoming.length === 0) {
            list.innerHTML = '<div class="sat-no-passes">No passes predicted in next 24h</div>';
            return;
        }

        upcoming.forEach(function (p) {
            var item = document.createElement("div");
            item.className = "sat-pass-item";

            var aosDate = new Date(p.aos);
            var timeStr = aosDate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
            var dateStr = aosDate.toLocaleDateString([], { month: "short", day: "numeric" });

            var elevClass = p.max_elevation >= 60 ? "elev-high" :
                            p.max_elevation >= 40 ? "elev-mid" : "elev-low";

            item.innerHTML =
                '<div class="sat-pass-info">' +
                    '<span class="sat-name">' + p.satellite + '</span>' +
                    '<span class="sat-time">' + dateStr + ' ' + timeStr + '</span>' +
                '</div>' +
                '<div class="sat-pass-meta">' +
                    '<span class="sat-elev ' + elevClass + '">' + p.max_elevation + '°</span>' +
                    '<span class="sat-duration">' + Math.round(p.duration / 60) + 'min</span>' +
                '</div>';

            list.appendChild(item);
        });
    };

    SatellitePanel.prototype._startCountdown = function () {
        var self = this;
        if (this.countdownInterval) clearInterval(this.countdownInterval);

        this.countdownInterval = setInterval(function () {
            self._updateCountdown();
        }, 1000);
        this._updateCountdown();
    };

    SatellitePanel.prototype._updateCountdown = function () {
        var el = document.getElementById("sat-countdown");
        if (!el) return;

        if (this.passes.length === 0) {
            el.textContent = "--:--:--";
            return;
        }

        var now = new Date();
        var nextAos = new Date(this.passes[0].aos);
        var diff = Math.max(0, Math.floor((nextAos - now) / 1000));

        if (diff <= 0) {
            el.textContent = "NOW";
            el.classList.add("sat-countdown-now");
            return;
        }

        el.classList.remove("sat-countdown-now");
        var h = Math.floor(diff / 3600);
        var m = Math.floor((diff % 3600) / 60);
        var s = diff % 60;
        el.textContent =
            (h > 0 ? h + "h " : "") +
            (m < 10 ? "0" : "") + m + ":" +
            (s < 10 ? "0" : "") + s;
    };

    SatellitePanel.prototype._updateRecordingStatus = function (status) {
        var indicator = document.getElementById("sat-recording-indicator");
        var progress = document.getElementById("sat-recording-progress");
        if (!indicator || !progress) return;

        if (status.apt_recording) {
            indicator.classList.remove("hidden");
            indicator.classList.add("recording");
            if (!this.recordingStart) {
                this.recordingStart = new Date();
                this.recordingDuration = this.passes.length > 0 ? this.passes[0].duration : 900;
                this._startRecordingProgress();
            }
        } else {
            indicator.classList.add("hidden");
            indicator.classList.remove("recording");
            this.recordingStart = null;
            if (this.recordingInterval) {
                clearInterval(this.recordingInterval);
                this.recordingInterval = null;
            }
            progress.style.width = "0%";
        }
    };

    SatellitePanel.prototype._startRecordingProgress = function () {
        var self = this;
        if (this.recordingInterval) clearInterval(this.recordingInterval);

        this.recordingInterval = setInterval(function () {
            var progress = document.getElementById("sat-recording-progress");
            if (!progress || !self.recordingStart) return;

            var elapsed = (new Date() - self.recordingStart) / 1000;
            var pct = Math.min(100, (elapsed / self.recordingDuration) * 100);
            progress.style.width = pct + "%";
        }, 1000);
    };

    SatellitePanel.prototype._onPassUpcoming = function (data) {
        this._fetchPasses();
        var label = document.getElementById("sat-next-label");
        if (label) {
            label.textContent = data.satellite + " in " + data.minutes_until + " min";
        }
    };

    SatellitePanel.prototype._onImageReady = function (data) {
        this._displayImage(data);
        this._fetchPasses();
    };

    SatellitePanel.prototype._displayImage = function (data) {
        var container = document.getElementById("sat-latest-image");
        if (!container) return;

        container.innerHTML =
            '<div class="sat-image-meta">' +
                '<span class="sat-name">' + (data.satellite || "") + '</span>' +
                '<span class="sat-image-time">' + (data.pass_time || "") + '</span>' +
            '</div>' +
            '<img src="' + data.url + '" alt="APT satellite image" class="sat-decoded-img" ' +
                'onclick="this.classList.toggle(\'expanded\')">';

        // Update history
        this._fetchImageHistory();
    };

    SatellitePanel.prototype._fetchImageHistory = function () {
        // Re-fetch latest image list by loading page images from static dir
        // We piggyback on the latest-image endpoint since history is limited
        var historyEl = document.getElementById("sat-image-history");
        if (!historyEl) return;

        fetch("/api/satellite/latest-image")
            .then(function (r) {
                if (r.ok) return r.json();
                return null;
            })
            .then(function (data) {
                if (!data) return;
                // For now show the latest as a thumbnail
                historyEl.innerHTML =
                    '<div class="sat-thumb" onclick="document.getElementById(\'sat-latest-image\').scrollIntoView()">' +
                        '<img src="' + data.url + '" alt="' + data.satellite + '">' +
                    '</div>';
            })
            .catch(function () {});
    };

    SatellitePanel.prototype.show = function () {
        var panel = document.getElementById("satellite-panel");
        if (panel) panel.classList.remove("hidden");
    };

    SatellitePanel.prototype.hide = function () {
        var panel = document.getElementById("satellite-panel");
        if (panel) panel.classList.add("hidden");
    };

    // Export
    window.SatellitePanel = SatellitePanel;
})();
