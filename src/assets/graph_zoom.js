// Comportamiento tipo "marcas en un mapa": los nodos, etiquetas y líneas
// mantienen un tamaño constante en píxeles de pantalla sin importar el zoom.
// Así, al acercarse, las distancias entre buses crecen (se separan los que se
// superponían) mientras las marcas conservan su tamaño — a diferencia de escalar
// una imagen estática, donde nodo y distancia crecen juntos y el solapamiento
// nunca cambia.
window.mgInstallMapZoom = function (divId) {
    var div = document.getElementById(divId);
    var cy = div && div._cyreg && div._cyreg.cy;
    if (!cy) return;

    // Tamaños base en píxeles de pantalla (a zoom = 1).
    var BASE = { node: 42, font: 9, border: 2, slack: 4, edge: 4, trafo: 5, edgeFont: 8, textMax: 80 };

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
            cy.edges().style({ 'width': BASE.edge / z, 'font-size': BASE.edgeFont / z });
            cy.edges('.trafo').style({ 'width': BASE.trafo / z });
        });
    };

    if (!cy._mapHooked) {
        cy._mapHooked = true;
        cy.on('zoom', reescalar);
    }
    reescalar();
};
