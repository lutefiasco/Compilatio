// Front page JavaScript

document.addEventListener('DOMContentLoaded', () => {
    console.log('Compilatio project loaded!');

    // Add fade-in animation
    const container = document.querySelector('.container');
    if (container) {
        container.style.opacity = '0';
        container.style.transition = 'opacity 0.5s ease-in';
        setTimeout(() => {
            container.style.opacity = '1';
        }, 100);
    }
});
