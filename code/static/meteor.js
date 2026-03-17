// Meteor scatter panel — real-time event feed, rate chart, shower context, stats

(function () {
    "use strict";

    function MeteorPanel(socket) {
        this.socket = socket;
        this.events = [];
        this.stats = {};
        this.showers = [];
        this.canvas = null;
        this.ctx = null;

        this._bindEvents();
        this._fetchEvents();
        this._fetchStats();
        this._fetchShowers();
    }

    MeteorPanel.prototype._bindEvents = function () {
        var self = this;

        this.socket.on("meteor_detection", function (data) {
            self._onDetection(data);
        });

        this.socket.on("meteor_stats_update", function (data) {
            self.stats = data;
            self._renderStats();
            self._renderRateChart();
        });
    };

    MeteorPanel.prototype._fetchEvents = function () {
        var self = this;
        fetch("/api/meteor/events?limit=50")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (Array.isArray(data)) {
                    self.events = data;
                    self._renderEventFeed();
                }
            })
            .catch(function () {});
    };

    MeteorPanel.prototype._fetchStats = function () {
        var self = this;
        fetch("/api/meteor/stats")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                self.stats = data;
                self._renderStats();
                self._renderRateChart();
                self._renderShowerContext();
            })
            .catch(function () {});
    };

    MeteorPanel.prototype._fetchShowers = function () {
        var self = this;
        fetch("/api/meteor/showers")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (Array.isArray(data)) {
                    self.showers = data;
                }
            })
            .catch(function () {});
    };

    MeteorPanel.prototype._onDetection = function (data) {
        // Prepend new detection to event list
        this.events.unshift(data);
        if (this.events.length > 100) {
            this.events = this.events.slice(0, 100);
        }
        this._renderEventFeed();

        // Update count display
        var countEl = document.getElementById("meteor-today-count");
        if (countEl) {
            var val = parseInt(countEl.textContent) || 0;
            countEl.textContent = val + 1;
        }
    };

    MeteorPanel.prototype._renderEventFeed = function () {
        var feed = document.getElementById("meteor-event-feed");
        if (!feed) return;

        while (feed.firstChild) feed.removeChild(feed.firstChild);

        if (this.events.length === 0) {
            var noData = document.createElement("div");
            noData.className = "meteor-no-data";
            noData.textContent = "No detections yet";
            feed.appendChild(noData);
            return;
        }

        var self = this;
        this.events.slice(0, 50).forEach(function (evt, idx) {
            var item = document.createElement("div");
            item.className = "meteor-event-item";
            if (idx === 0) item.classList.add("meteor-event-new");

            var ts = document.createElement("span");
            ts.className = "meteor-event-ts";
            ts.textContent = (evt.timestamp || "").substring(11, 23);
            item.appendChild(ts);

            var dur = document.createElement("span");
            dur.className = "meteor-event-dur";
            dur.textContent = (evt.duration_ms || 0) + "ms";
            item.appendChild(dur);

            var badge = document.createElement("span");
            badge.className = "meteor-trail-badge meteor-trail-" + (evt.trail_type || "underdense");
            badge.textContent = evt.trail_type === "overdense" ? "O" : "U";
            item.appendChild(badge);

            var power = document.createElement("span");
            power.className = "meteor-event-power";
            power.textContent = (evt.peak_power_dbm || 0).toFixed(1) + " dBm";
            item.appendChild(power);

            if (evt.shower) {
                var shower = document.createElement("span");
                shower.className = "meteor-event-shower";
                shower.textContent = evt.shower;
                item.appendChild(shower);
            }

            feed.appendChild(item);
        });
    };

    MeteorPanel.prototype._renderStats = function () {
        var stats = this.stats;
        var el;

        el = document.getElementById("meteor-today-count");
        if (el) el.textContent = stats.total || 0;

        el = document.getElementById("meteor-peak-rate");
        if (el) el.textContent = (stats.peak_hourly_rate || 0) + "/hr";

        el = document.getElementById("meteor-ud-ratio");
        if (el) {
            var ratio = stats.underdense_ratio || 0;
            el.textContent = Math.round(ratio * 100) + "% U";
        }

        el = document.getElementById("meteor-session-hrs");
        if (el) el.textContent = (stats.session_hours || 0).toFixed(1) + "h";

        el = document.getElementById("meteor-baseline");
        if (el && stats.baseline_dbm !== undefined) {
            el.textContent = stats.baseline_dbm + " dBm";
        }

        el = document.getElementById("meteor-frequency");
        if (el && stats.frequency_hz) {
            el.textContent = (stats.frequency_hz / 1e6).toFixed(3) + " MHz";
        }
    };

    MeteorPanel.prototype._renderShowerContext = function () {
        var el = document.getElementById("meteor-shower-info");
        if (!el) return;

        while (el.firstChild) el.removeChild(el.firstChild);

        var stats = this.stats;

        if (stats.shower) {
            var name = document.createElement("span");
            name.className = "meteor-shower-name";
            name.textContent = stats.shower + " active";
            el.appendChild(name);
        } else if (stats.next_shower) {
            var next = stats.next_shower;
            var text = document.createElement("span");
            text.className = "meteor-shower-next";
            text.textContent = next.name + " in " + next.days_until + " days (ZHR " + next.zhr + ")";
            el.appendChild(text);
        } else {
            var sporadic = document.createElement("span");
            sporadic.className = "meteor-shower-sporadic";
            sporadic.textContent = "Sporadic background";
            el.appendChild(sporadic);
        }
    };

    MeteorPanel.prototype._renderRateChart = function () {
        if (!this.canvas) {
            this.canvas = document.getElementById("meteor-rate-canvas");
            if (!this.canvas) return;
            this.ctx = this.canvas.getContext("2d");
        }

        var hourly = (this.stats && this.stats.hourly) ? this.stats.hourly : [];
        if (hourly.length === 0) return;

        var canvas = this.canvas;
        var ctx = this.ctx;
        var w = canvas.width;
        var h = canvas.height;
        var padding = { top: 10, right: 10, bottom: 20, left: 30 };

        ctx.clearRect(0, 0, w, h);

        var chartW = w - padding.left - padding.right;
        var chartH = h - padding.top - padding.bottom;
        var maxCount = Math.max(1, Math.max.apply(null, hourly.map(function (h) { return h.count; })));
        var barW = Math.max(2, chartW / hourly.length - 1);

        // Draw bars
        hourly.forEach(function (entry, i) {
            var barH = (entry.count / maxCount) * chartH;
            var x = padding.left + (i / hourly.length) * chartW;
            var y = padding.top + chartH - barH;

            ctx.fillStyle = entry.count > 0 ? "#3fb950" : "#21262d";
            ctx.fillRect(x, y, barW, barH);
        });

        // Y-axis label
        ctx.fillStyle = "#8b949e";
        ctx.font = "9px monospace";
        ctx.textAlign = "right";
        ctx.fillText(maxCount.toString(), padding.left - 4, padding.top + 9);
        ctx.fillText("0", padding.left - 4, padding.top + chartH);

        // X-axis labels (every 6 hours)
        ctx.textAlign = "center";
        for (var i = 0; i < hourly.length; i += 6) {
            var x = padding.left + (i / hourly.length) * chartW + barW / 2;
            var label = (hourly[i].hour || "").substring(11, 13) + "h";
            ctx.fillText(label, x, h - 4);
        }
    };

    MeteorPanel.prototype.show = function () {
        var panel = document.getElementById("meteor-panel");
        if (panel) panel.classList.remove("hidden");
    };

    MeteorPanel.prototype.hide = function () {
        var panel = document.getElementById("meteor-panel");
        if (panel) panel.classList.add("hidden");
    };

    // Export
    window.MeteorPanel = MeteorPanel;
})();
