import { registerPush } from './notifications.js';
import { render_ascii_title } from './utils.js';

const enableBtn = document.getElementById('enableNotificationsBtn');
const skipBtn = document.getElementById('skipNotificationsBtn');
const asciiTitle = document.getElementById('ascii-title');

function getIndexPage() {
    window.location.href = '/';
}

enableBtn.addEventListener('click', async () => {
    await registerPush();
    getIndexPage();
});

skipBtn.addEventListener('click', () => {
    getIndexPage();
});

render_ascii_title(asciiTitle, 'FDM Sentinel');