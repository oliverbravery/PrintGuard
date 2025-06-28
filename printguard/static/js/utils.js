export { render_ascii_title };

function render_ascii_title(doc_element, text) {
    figlet.defaults({ fontPath: '/static/fonts/' });
    figlet.text(text, {
        font: 'Big Money-ne',
        horizontalLayout: 'default',
        verticalLayout: 'default'
    }, function(err, data) {
        if (err) {
            console.error(err);
            return;
        }
        doc_element.textContent = data;
    });
}