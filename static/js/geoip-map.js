/*
 * GeoIP click-to-select world map (v3.17.522).
 *
 * Progressive enhancement over the country text inputs that were there before:
 * the map writes comma-separated ISO alpha-2 codes back into the same hidden
 * inputs the form already posted, so the server contract is unchanged and the
 * page still works with JavaScript disabled.
 *
 * Requires jsVectorMap + its world map, loaded by the including template.
 */
(function () {
  'use strict';

  function parseCodes(value) {
    return (value || '')
      .split(',')
      .map(function (c) { return c.trim().toUpperCase(); })
      .filter(Boolean);
  }

  function initMap(wrap) {
    var mapId = wrap.dataset.mapId;
    var el = document.getElementById(mapId);
    if (!el || typeof window.jsVectorMap === 'undefined') { return; }

    var lists;
    try { lists = JSON.parse(wrap.dataset.lists || '[]'); } catch (e) { return; }
    if (!lists.length) { return; }

    // Seed each list from its hidden input when present, so a server-side
    // value (or a failed form re-render) wins over the markup default.
    lists.forEach(function (list) {
      var input = document.getElementById(list.input_id);
      list.codes = input ? parseCodes(input.value) : (list.codes || []);
      list.codes = list.codes.map(function (c) { return c.toUpperCase(); });
    });

    var active = 0;

    function ownerOf(code) {
      for (var i = 0; i < lists.length; i++) {
        if (lists[i].codes.indexOf(code) !== -1) { return i; }
      }
      return -1;
    }

    function syncInputs() {
      lists.forEach(function (list) {
        var input = document.getElementById(list.input_id);
        if (input) {
          input.value = list.codes.join(',');
          // Let any other listeners (dirty-form tracking) know.
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }
      });
    }

    function paint() {
      var values = {};
      lists.forEach(function (list) {
        list.codes.forEach(function (code) { values[code] = list.color; });
      });
      map.series.regions[0].setValues(values);
      renderLegend();
    }

    function renderLegend() {
      var legend = wrap.querySelector('.geoip-map-legend');
      if (!legend) { return; }
      legend.innerHTML = lists.map(function (list) {
        return '<span class="me-3"><span class="geoip-swatch" style="background:' +
          list.color + '"></span>' + list.label + ': <strong>' +
          list.codes.length + '</strong></span>';
      }).join('');
    }

    function toggle(code) {
      code = (code || '').toUpperCase();
      if (!code) { return; }
      var owner = ownerOf(code);
      if (owner === active) {
        // Already in the active list -> deselect.
        lists[active].codes = lists[active].codes.filter(function (c) { return c !== code; });
      } else {
        // Move it out of any other list first: a country belongs to one list,
        // which is what prevents an "allowed AND blocked" contradiction.
        if (owner !== -1) {
          lists[owner].codes = lists[owner].codes.filter(function (c) { return c !== code; });
        }
        lists[active].codes.push(code);
      }
      syncInputs();
      paint();
    }

    var map = new window.jsVectorMap({
      selector: '#' + mapId,
      map: 'world',
      backgroundColor: 'transparent',
      zoomButtons: true,
      regionStyle: {
        initial: { fill: '#c8d2dc', stroke: '#ffffff', strokeWidth: 0.4 },
        hover: { fillOpacity: 0.85, cursor: 'pointer' }
      },
      series: { regions: [{ attribute: 'fill', values: {} }] },
      onRegionClick: function (event, code) { toggle(code); }
    });

    // Mode switcher — only meaningful with more than one list.
    var modes = wrap.querySelector('.geoip-map-modes');
    if (modes) {
      if (lists.length > 1) {
        lists.forEach(function (list, i) {
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'btn btn-outline-secondary' + (i === 0 ? ' active' : '');
          btn.innerHTML = '<span class="geoip-swatch" style="background:' + list.color + '"></span>' + list.label;
          btn.addEventListener('click', function () {
            active = i;
            modes.querySelectorAll('.btn').forEach(function (b) { b.classList.remove('active'); });
            btn.classList.add('active');
          });
          modes.appendChild(btn);
        });
      } else {
        modes.remove();
      }
    }

    var clear = wrap.querySelector('.geoip-map-clear');
    if (clear) {
      clear.addEventListener('click', function () {
        lists[active].codes = [];
        syncInputs();
        paint();
      });
    }

    // Typing in the text inputs keeps the map in step, so neither input
    // method silently overrides the other.
    lists.forEach(function (list, i) {
      var input = document.getElementById(list.input_id);
      if (!input) { return; }
      input.addEventListener('input', function () {
        lists[i].codes = parseCodes(input.value);
        paint();
      });
    });

    paint();
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-geoip-map]').forEach(initMap);
  });
})();
