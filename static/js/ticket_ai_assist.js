/*
 * Ticket AI Assist panel: "Analyze ticket" and "Compare models".
 *
 * 1. Preview: shows exactly what would be sent (redacted evidence, what was
 *    left out), where (the paired rem0te, each model, cloud or on-premises)
 *    and the estimated cost. Nothing is sent until the technician confirms.
 * 2. Submit, then poll the job until it finishes.
 * 3. Results: facts with their evidence IDs, likely causes, missing
 *    information, checks, warnings and draft replies. Compared models are
 *    shown side by side with disagreements labelled; a model that failed
 *    shows its error while the others still show their results.
 *
 * Every string from the server — ticket text and model output alike — is
 * written with textContent, never as HTML. "Use reply" only places text in
 * the composer (window.ticketComposerInsert); the composer's Send is the
 * only thing that publishes.
 */
(function () {
    'use strict';
    var panel = document.getElementById('aiAssistPanel');
    if (!panel) { return; }
    var canSend = panel.dataset.canSend === '1';
    var pollTimer = null;

    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            if (k === 'text') { node.textContent = attrs[k]; } else if (k === 'class') { node.className = attrs[k]; } else { node.setAttribute(k, attrs[k]); }
        });
        (children || []).forEach(function (c) { if (c) { node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); } });
        return node;
    }
    function csrf() {
        var t = document.querySelector('[name=csrfmiddlewaretoken]');
        return t ? t.value : '';
    }
    function show(nodes) {
        panel.replaceChildren.apply(panel, nodes);
        panel.classList.remove('d-none');
    }
    function fail(msg) {
        show([el('div', {class: 'alert alert-warning mb-0', text: msg})]);
    }
    function list(title, items, render) {
        if (!items || !items.length) { return null; }
        return el('div', {class: 'mb-2'}, [el('div', {class: 'fw-semibold', text: title}),
            el('ul', {class: 'mb-1 ps-3'}, items.map(function (i) { return el('li', {}, render(i)); }))]);
    }
    function refs(ids) {
        return (ids || []).length ? el('span', {class: 'text-muted ms-1', text: '[' + ids.join(', ') + ']'}) : null;
    }

    function preview(mode) {
        fetch(panel.dataset.previewUrl + '?mode=' + encodeURIComponent(mode), {credentials: 'same-origin'})
            .then(function (r) { return r.json(); })
            .then(function (d) { renderPreview(d); })
            .catch(function () { fail('Could not load the preview.'); });
    }

    function renderPreview(d) {
        if (!d.available) {
            show([el('div', {class: 'alert alert-secondary mb-0'}, [el('strong', {text: 'Not available: '}), (d.reasons || []).join(' ')])]);
            return;
        }
        var nodes = [el('div', {class: 'fw-semibold mb-1', text: d.mode === 'compare' ? 'Compare models — review before sending' : 'Analyze ticket — review before sending'})];
        nodes.push(el('div', {class: 'mb-2'}, ['Processed by ', el('strong', {text: d.processor.name}), ' (' + d.processor.site + ', ' + (d.processor.location === 'local' ? 'on-premises' : 'hosted') + ').']));
        var picks = [];
        var models = d.mode === 'compare' ? d.choosable : d.profiles;
        nodes.push(el('div', {class: 'fw-semibold', text: d.mode === 'compare' ? 'Models (each one receives the evidence):' : 'Model:'}));
        models.forEach(function (p) {
            var line = [p.name + ' — ' + p.provider + ' ' + p.model + ', ' + p.location + ', ' + p.credential + ' key, about $' + (p.estimated_cost_cents / 100).toFixed(4)];
            if (d.mode === 'compare') {
                var box = el('input', {type: 'checkbox', class: 'form-check-input me-1', value: String(p.id)});
                box.checked = d.profiles.some(function (x) { return x.id === p.id; });
                picks.push(box);
                nodes.push(el('label', {class: 'd-block'}, [box].concat(line)));
            } else {
                nodes.push(el('div', {}, line));
            }
        });
        if (d.budget_remaining_cents !== null) {
            nodes.push(el('div', {class: 'text-muted mb-2', text: 'Budget left today for this customer: $' + (d.budget_remaining_cents / 100).toFixed(2)}));
        }
        var ev = el('details', {class: 'mb-2'}, [el('summary', {text: 'Evidence to be sent (' + d.evidence.items.length + ' items, redacted)'})]);
        d.evidence.items.forEach(function (i) {
            ev.appendChild(el('div', {class: 'border-start ps-2 mb-1'}, [el('code', {text: i.id}), ' ' + i.kind + (i.role ? ' (' + i.role + ')' : '') + ': ', el('span', {text: i.text})]));
        });
        nodes.push(ev);
        var ex = d.evidence.excluded, red = d.evidence.redactions;
        nodes.push(el('div', {class: 'text-muted mb-2', text: 'Not sent: ' + ex.internal_notes + ' internal note(s), ' + ex.attachments + ' attachment(s), ' + ex.older_comments + ' older comment(s); vault data, raw RMM data and remote-session data are never sent.' + (Object.keys(red).length ? ' Redacted: ' + Object.keys(red).map(function (k) { return red[k] + ' ' + k; }).join(', ') + '.' : '')}));
        if (!d.evidence.asset.linked) {
            nodes.push(el('div', {class: 'text-muted mb-2', text: 'No device is linked; the analysis works from the ticket alone.'}));
        }
        var go = el('button', {type: 'button', class: 'btn btn-sm btn-primary me-1', text: 'Send for analysis'});
        var cancel = el('button', {type: 'button', class: 'btn btn-sm btn-outline-secondary', text: 'Cancel'});
        cancel.addEventListener('click', function () { panel.classList.add('d-none'); });
        go.addEventListener('click', function () {
            go.disabled = true;
            var ids = picks.filter(function (b) { return b.checked; }).map(function (b) { return Number(b.value); });
            submit({mode: d.mode, idempotency_key: d.idempotency_key, evidence_digest: d.evidence_digest, profile_ids: ids});
        });
        nodes.push(el('div', {}, [go, cancel]));
        show(nodes);
    }

    function submit(body) {
        fetch(panel.dataset.submitUrl, {method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()}, body: JSON.stringify(body)})
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.ok) { fail(d.error || 'The analysis could not start.'); return; }
                show([el('div', {class: 'text-muted', text: 'Analysis requested. Waiting for results…'})]);
                poll(d.job_id, 0);
            })
            .catch(function () { fail('The analysis could not start.'); });
    }

    function poll(jobId, n) {
        clearTimeout(pollTimer);
        fetch(panel.dataset.jobUrl.replace('00000000-0000-0000-0000-000000000000', jobId), {credentials: 'same-origin'})
            .then(function (r) { return r.json(); })
            .then(function (d) {
                renderJob(d);
                if (!d.terminal && n < 120) { pollTimer = setTimeout(function () { poll(jobId, n + 1); }, n < 10 ? 2000 : 5000); }
            })
            .catch(function () { fail('Lost contact while waiting for results. Reload to check again.'); });
    }

    function renderRun(run, jobId) {
        var head = el('div', {class: 'fw-semibold mb-1'}, [run.profile + ' (' + run.provider + ')', run.cost_cents ? el('span', {class: 'text-muted ms-1', text: '$' + (run.cost_cents / 100).toFixed(4)}) : null]);
        if (run.status !== 'succeeded') {
            return el('div', {class: 'col'}, [head, el('div', {class: 'text-danger', text: run.status === 'pending' || run.status === 'dispatched' || run.status === 'executing' ? 'Running…' : (run.error || 'No result.')})]);
        }
        var r = run.result;
        var parts = [head,
            list('Observed facts', r.observed_facts, function (f) { return [f.text, refs(f.evidence)]; }),
            list('Likely causes', r.likely_causes, function (c) { return [el('span', {class: 'badge bg-light text-dark me-1', text: c.likelihood}), c.text, refs(c.evidence)]; }),
            list('Missing information', r.missing_information, function (t) { return [t]; }),
            list('Suggested checks (for you to do; nothing is run)', r.suggested_checks, function (c) { return [c.text]; }),
            list('Warnings', r.warnings, function (t) { return [el('span', {class: 'text-warning-emphasis', text: t})]; })];
        (r.customer_replies || []).forEach(function (rep, idx) {
            var text = el('textarea', {class: 'form-control form-control-sm mb-1', rows: '4'});
            text.value = rep.text;
            var use = el('button', {type: 'button', class: 'btn btn-sm btn-outline-primary', text: canSend ? 'Use reply' : 'Use as internal note'});
            use.title = canSend ? 'Place this draft in the reply box. Nothing is sent until you press Send.'
                : 'Your access does not include sending AI-assisted replies; the draft goes into an internal note.';
            use.addEventListener('click', function () {
                var outcome = window.ticketComposerInsert ? window.ticketComposerInsert(text.value, 'job:' + jobId + ':' + idx, !canSend) : '';
                use.textContent = outcome === 'appended' ? 'Added below your text' : (outcome ? 'In the reply box' : 'No reply box');
            });
            parts.push(el('div', {class: 'mb-2'}, [el('div', {class: 'fw-semibold', text: 'Draft reply: ' + rep.label}), text, use]));
        });
        return el('div', {class: 'col'}, parts);
    }

    function renderJob(d) {
        var nodes = [el('div', {class: 'd-flex justify-content-between mb-2'}, [
            el('span', {class: 'badge bg-warning text-dark', text: 'AI-generated — staff only, verify before acting'}),
            el('span', {class: 'text-muted', text: d.status_label})])];
        if (d.stale) { nodes.push(el('div', {class: 'alert alert-info py-1', text: 'The ticket changed after this analysis was requested.'})); }
        (d.disagreements || []).forEach(function (x) { nodes.push(el('div', {class: 'alert alert-secondary py-1', text: 'Disagreement: ' + x.detail})); });
        if (d.terminal && d.error && !(d.runs || []).some(function (r) { return r.status === 'succeeded'; })) {
            nodes.push(el('div', {class: 'alert alert-warning py-1', text: d.error}));
        }
        nodes.push(el('div', {class: 'row row-cols-1 row-cols-lg-' + Math.min(Math.max(d.runs.length, 1), 3) + ' g-3'}, d.runs.map(function (r) { return renderRun(r, d.job_id); })));
        show(nodes);
    }

    document.querySelectorAll('[data-ai-assist]').forEach(function (b) {
        b.addEventListener('click', function () { preview(b.getAttribute('data-ai-assist')); });
    });
})();
