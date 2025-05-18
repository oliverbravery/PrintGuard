import { registerPush } from './notifications.js';

const enableBtn = document.getElementById('enableNotificationsBtn');
const skipBtn = document.getElementById('skipNotificationsBtn');

function getIndexPage() {
    window.location.href = '/';
}

enableBtn.addEventListener('click', async () => {
    await registerPush();
    localStorage.setItem('onboardingComplete', 'true');
    getIndexPage();
});

skipBtn.addEventListener('click', () => {
    localStorage.setItem('onboardingComplete', 'true');
    getIndexPage();
});