// New-ticket asset picker: reload the asset list when the client changes,
// so only the chosen client's assets can be picked. The server checks the
// asset belongs to the client again on submit.
(function () {
    'use strict';
    document.addEventListener('DOMContentLoaded', function () {
        var asset = document.getElementById('ticket-asset');
        var client = document.querySelector('select[name="client"]');
        if (!asset || !client) return;
        var url = asset.getAttribute('data-assets-url');

        function fill(list) {
            while (asset.options.length > 1) asset.remove(1);
            list.forEach(function (a) {
                var label = a.name + (a.hostname && a.hostname !== a.name ? ' (' + a.hostname + ')' : '');
                asset.add(new Option(label, a.id));
            });
        }

        client.addEventListener('change', function () {
            fill([]);
            if (!client.value) return;
            fetch(url + '?client=' + encodeURIComponent(client.value), {credentials: 'same-origin'})
                .then(function (r) { return r.ok ? r.json() : {assets: []}; })
                .then(function (data) { fill(data.assets || []); })
                .catch(function () { fill([]); });
        });
    });
})();
