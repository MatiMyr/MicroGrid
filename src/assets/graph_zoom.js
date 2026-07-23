// Comportamiento tipo "marcas en un mapa": los nodos, etiquetas y líneas
// mantienen un tamaño constante en píxeles de pantalla sin importar el zoom.
// Así, al acercarse, las distancias entre buses crecen (se separan los que se
// superponían) mientras las marcas conservan su tamaño — a diferencia de escalar
// una imagen estática, donde nodo y distancia crecen juntos y el solapamiento
// nunca cambia.
window.mgInstallMapZoom = function (divId, _tries) {
    _tries = _tries || 0;
    var div = document.getElementById(divId);
    var cy = div && div._cyreg && div._cyreg.cy;
    // La instancia de Cytoscape puede no estar lista todavía (p. ej. al montar el
    // grafo al cambiar de pestaña). Reintentar hasta que exista, si no el hook
    // nunca se instala y el zoom/pan/grilla quedan sin funcionar en esa vista.
    if (!cy) {
        if (_tries < 60) {
            setTimeout(function () { window.mgInstallMapZoom(divId, _tries + 1); }, 100);
        }
        return;
    }

    // Tamaños base en píxeles de pantalla (a zoom = 1).
    var BASE = { node: 42, font: 9, border: 2, slack: 4, edge: 4, trafo: 5, edgeFont: 8, textMax: 80 };
    var GRID = 40; // paso de la grilla en unidades de modelo

    var reescalar = function () {
        var z = cy.zoom() || 1;
        cy.batch(function () {
            cy.nodes().style({
                'width': BASE.node / z,
                'height': BASE.node / z,
                'font-size': BASE.font / z,
                'border-width': BASE.border / z,
                'text-max-width': (BASE.textMax / z)
            });
            cy.nodes('.slack').style({ 'border-width': BASE.slack / z });
            cy.nodes('.sel').style({ 'border-width': 6 / z, 'border-color': '#2a78d6', 'overlay-padding': 8 / z });
            cy.edges().style({ 'width': BASE.edge / z, 'font-size': BASE.edgeFont / z });
            cy.edges('.trafo').style({ 'width': BASE.trafo / z });
        });
    };

    // Grilla de fondo que se mueve y escala con el grafo (referencia al hacer zoom).
    var actualizarGrilla = function () {
        var z = cy.zoom() || 1;
        var p = cy.pan() || { x: 0, y: 0 };
        var s = GRID * z;
        div.style.backgroundSize = s + 'px ' + s + 'px, ' + s + 'px ' + s + 'px';
        div.style.backgroundPosition = p.x + 'px ' + p.y + 'px, ' + p.x + 'px ' + p.y + 'px';
    };

    if (!cy._mapHooked) {
        cy._mapHooked = true;
        // El tamaño de las marcas depende del zoom.
        cy.on('zoom', function () { reescalar(); actualizarGrilla(); });
        // La grilla debe seguir el viewport en CADA frame de pan/zoom. 'render'
        // se dispara por frame durante el paneo y no genera loop (solo toca CSS,
        // no el estado de cytoscape). 'layoutstop' cubre el fit inicial.
        cy.on('render pan', actualizarGrilla);
        cy.on('layoutstop', function () { reescalar(); actualizarGrilla(); });
    }
    reescalar();
    actualizarGrilla();
};

// Instalación autónoma (no depende de callbacks de Dash, que no se disparan de
// forma confiable al montar un grafo al cambiar de pestaña). Un intervalo
// engancha ambos grafos apenas su instancia de Cytoscape existe, y reengancha
// tras un re-montaje (nuevo cy sin las banderas). Es idempotente.
(function () {
    function ensure() {
        ['ed-graph', 'db-graph'].forEach(function (id) {
            var div = document.getElementById(id);
            var cy = div && div._cyreg && div._cyreg.cy;
            if (!cy) return;
            if (!cy._mapHooked) { window.mgInstallMapZoom(id); }
            // El Editor: al soltar un bus arrastrado, reenviar 'dragfree' como
            // 'tap' para que se guarde la posición (Input tapNode).
            if (id === 'ed-graph' && !cy._dragHooked) {
                cy._dragHooked = true;
                cy.on('dragfree', 'node', function (e) { e.target.emit('tap'); });
            }
        });
    }
    function start() { ensure(); setInterval(ensure, 400); }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
