/**
 * quiz.js — Anti-Cheat Quiz Engine
 * Handles: timer, violations, fullscreen, answer tracking, submission
 */

(function () {
    'use strict';

    /* ── State ───────────────────────────────────── */
    const answers = {};          // { question_id: "A"|"B"|... }
    let currentQ = 1;
    let violations = 0;
    let timerSeconds = REMAINING_SECONDS;
    let timerInterval = null;
    let submitting = false;
    let quizStartTime = Date.now();

    /* ── DOM refs ────────────────────────────────── */
    const timerEl = document.getElementById('timerDisplay');
    const violOverlay = document.getElementById('violationOverlay');
    const violMsg = document.getElementById('violationMsg');
    const violCountEl = document.getElementById('violCount');
    const maxViolEl = document.getElementById('maxViol');
    const violBadge = document.getElementById('violBadge');
    const submitOverlay = document.getElementById('submitOverlay');
    const confirmModal = document.getElementById('confirmModal');
    const progressFill = document.getElementById('progressFill');
    const qIndicator = document.getElementById('questionIndicator');
    const answeredCountEl = document.getElementById('answeredCount');

    /* ── Init ────────────────────────────────────── */
    maxViolEl.textContent = MAX_VIOLATIONS;
    updateProgress();
    requestFullscreen();
    startTimer();
    setupAntiCheat();
    disableContextMenu();

    /* ── Timer ───────────────────────────────────── */
    function startTimer() {
        updateTimerDisplay();
        timerInterval = setInterval(() => {
            timerSeconds--;
            updateTimerDisplay();
            if (timerSeconds <= 0) {
                clearInterval(timerInterval);
                doSubmit(true, 'time_expired');
            }
            if (timerSeconds <= 60) {
                document.getElementById('quizTimer').classList.add('timer-critical');
            } else if (timerSeconds <= 300) {
                document.getElementById('quizTimer').classList.add('timer-warning');
            }
        }, 1000);
    }

    function updateTimerDisplay() {
        const m = Math.floor(timerSeconds / 60).toString().padStart(2, '0');
        const s = (timerSeconds % 60).toString().padStart(2, '0');
        timerEl.textContent = `${m}:${s}`;
    }

    /* ── Fullscreen ──────────────────────────────── */
    function requestFullscreen() {
        const el = document.documentElement;
        if (el.requestFullscreen) el.requestFullscreen();
        else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
        else if (el.mozRequestFullScreen) el.mozRequestFullScreen();
    }

    document.addEventListener('fullscreenchange', handleFsChange);
    document.addEventListener('webkitfullscreenchange', handleFsChange);

    function handleFsChange() {
        const inFs = !!(document.fullscreenElement || document.webkitFullscreenElement);
        if (!inFs && !submitting) {
            recordViolation('fullscreen_exit', 'Fullscreen exited');
        }
    }

    /* ── Anti-cheat: visibility & blur ──────────── */
    function setupAntiCheat() {
        document.addEventListener('visibilitychange', () => {
            if (document.hidden && !submitting) {
                recordViolation('tab_switch', 'You switched to another tab or minimized the browser.');
            }
        });

        window.addEventListener('blur', () => {
            if (!submitting) {
                // Debounce — only trigger if page is truly unfocused for 500ms
                setTimeout(() => {
                    if (!document.hasFocus() && !submitting) {
                        recordViolation('window_blur', 'Browser window lost focus.');
                    }
                }, 500);
            }
        });

        // Prevent right-click
        document.addEventListener('contextmenu', e => e.preventDefault());

        // Disable copy/paste/cut
        ['copy', 'cut', 'paste'].forEach(ev =>
            document.addEventListener(ev, e => e.preventDefault())
        );

        // Disable text selection via keyboard shortcuts
        document.addEventListener('keydown', e => {
            const blocked = ['F12', 'F5'];
            const ctrlKeys = ['a', 'c', 'v', 'x', 'u', 's', 'p', 'i', 'j'];
            if (blocked.includes(e.key)) { e.preventDefault(); return; }
            if ((e.ctrlKey || e.metaKey) && ctrlKeys.includes(e.key.toLowerCase())) {
                e.preventDefault();
            }
        });
    }

    function disableContextMenu() {
        document.addEventListener('selectstart', e => e.preventDefault());
        document.body.style.userSelect = 'none';
        document.body.style.webkitUserSelect = 'none';
    }

    /* ── Violation Engine ────────────────────────── */
    function recordViolation(type, msg) {
        if (submitting) return;
        violations++;
        violCountEl.textContent = violations;
        violBadge.textContent = `⚠ ${violations} violation${violations > 1 ? 's' : ''}`;
        violMsg.textContent = msg;
        violOverlay.classList.add('active');

        // Send to backend
        const device = navigator.userAgent.substring(0, 200);
        fetch('/api/violation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify({ type, device })
        })
            .then(r => r.json())
            .then(data => {
                if (data.auto_submit) {
                    dismissViolation();
                    doSubmit(true, 'violations');
                }
            })
            .catch(() => {
                if (violations >= MAX_VIOLATIONS) {
                    dismissViolation();
                    doSubmit(true, 'violations');
                }
            });
    }

    window.dismissViolation = function () {
        violOverlay.classList.remove('active');
        requestFullscreen();
    };

    /* ── Question Navigation ─────────────────────── */
    window.selectOption = function (btn, qid, opt) {
        answers[qid] = opt;
        // Clear previous selection for this question
        document.querySelectorAll(`#opts_${qid} .option-btn`).forEach(b => b.classList.remove('selected'));
        btn.classList.add('selected');
        // Mark dot answered
        const dot = document.getElementById(`dot_${currentQ}`);
        if (dot) dot.classList.add('dot-answered');
        autoSave();
    };

    window.goToQuestion = function (idx) {
        if (idx < 1 || idx > TOTAL_QUESTIONS) return;
        const prev = document.getElementById(`slide_${currentQ}`);
        const next = document.getElementById(`slide_${idx}`);
        if (prev) prev.classList.remove('active');
        if (next) next.classList.add('active');
        currentQ = idx;
        updateProgress();
        updateNavButtons();
    };

    window.nextQuestion = function () {
        if (currentQ < TOTAL_QUESTIONS) goToQuestion(currentQ + 1);
    };

    window.prevQuestion = function () {
        if (currentQ > 1) goToQuestion(currentQ - 1);
    };

    function updateProgress() {
        const pct = ((currentQ - 1) / TOTAL_QUESTIONS) * 100;
        progressFill.style.width = `${pct}%`;
        qIndicator.textContent = `Q ${currentQ} / ${TOTAL_QUESTIONS}`;
        document.querySelectorAll('.nav-dot').forEach((d, i) => {
            d.classList.toggle('dot-active', i + 1 === currentQ);
        });
    }

    function updateNavButtons() {
        document.getElementById('prevBtn').disabled = currentQ === 1;
        document.getElementById('nextBtn').disabled = currentQ === TOTAL_QUESTIONS;
    }

    /* ── Auto-save ───────────────────────────────── */
    let saveTimeout = null;
    function autoSave() {
        clearTimeout(saveTimeout);
        saveTimeout = setTimeout(() => {
            fetch('/api/save-answers', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
                body: JSON.stringify({ answers })
            }).catch(() => { });
        }, 1500);
    }

    /* ── Submit ──────────────────────────────────── */
    window.confirmSubmit = function () {
        const answered = Object.keys(answers).length;
        answeredCountEl.textContent = answered;
        confirmModal.style.display = 'flex';
    };

    window.closeModal = function () {
        confirmModal.style.display = 'none';
    };

    window.doSubmit = function (auto = false, reason = '') {
        if (submitting) return;
        submitting = true;
        clearInterval(timerInterval);
        confirmModal.style.display = 'none';
        submitOverlay.style.display = 'flex';

        const timeTaken = Math.floor((Date.now() - quizStartTime) / 1000);
        fetch('/api/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify({
                answers,
                time_taken: timeTaken,
                auto_submit: auto,
                reason
            })
        })
            .then(r => r.json())
            .then(data => {
                if (data.redirect) {
                    window.location.href = data.redirect;
                }
            })
            .catch(() => {
                // Retry once
                setTimeout(() => window.location.href = '/result', 2000);
            });
    };

    /* ── Keyboard shortcuts for navigation ───────── */
    document.addEventListener('keydown', e => {
        if (e.key === 'ArrowRight' || e.key === 'Enter') nextQuestion();
        if (e.key === 'ArrowLeft') prevQuestion();
        if (['1', '2', '3', '4'].includes(e.key)) {
            const opts = ['A', 'B', 'C', 'D'];
            const slide = document.getElementById(`slide_${currentQ}`);
            if (!slide) return;
            const qid = slide.dataset.id;
            const btn = document.getElementById(`opt_${qid}_${opts[parseInt(e.key) - 1]}`);
            if (btn) selectOption(btn, qid, opts[parseInt(e.key) - 1]);
        }
    });

    updateNavButtons();
})();
