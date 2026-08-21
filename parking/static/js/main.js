document.addEventListener('DOMContentLoaded', () => {
    // Live Clock
    const clockElement = document.getElementById('live-clock');
    
    function updateClock() {
        const now = new Date();
        let hours = now.getHours();
        let minutes = now.getMinutes();
        let seconds = now.getSeconds();
        const ampm = hours >= 12 ? 'PM' : 'AM';
        
        hours = hours % 12;
        hours = hours ? hours : 12; // the hour '0' should be '12'
        minutes = minutes < 10 ? '0' + minutes : minutes;
        seconds = seconds < 10 ? '0' + seconds : seconds;
        
        const strTime = hours + ':' + minutes + ':' + seconds + ' ' + ampm;
        if(clockElement) {
            clockElement.textContent = strTime;
        }
    }
    
    setInterval(updateClock, 1000);
    updateClock();

    // Add subtle animation to stats cards on load
    const statCards = document.querySelectorAll('.stat-card');
    statCards.forEach((card, index) => {
        card.style.opacity = '0';
        card.style.transform = 'translateY(20px)';
        setTimeout(() => {
            card.style.transition = 'all 0.5s ease';
            card.style.opacity = '1';
            card.style.transform = 'translateY(0)';
        }, 100 * index);
    });

    // Apply template styles from data attributes to avoid editor linter errors
    const applyDynamicStyles = () => {
        // 1. Small India plate styles
        document.querySelectorAll('.india-plate-sm').forEach(el => {
            if (el.dataset.bg) el.style.setProperty('background-color', el.dataset.bg, 'important');
            if (el.dataset.color) el.style.setProperty('color', el.dataset.color, 'important');
        });

        // 3. Large India plate styles
        document.querySelectorAll('.india-plate').forEach(el => {
            const bg = el.dataset.bg;
            const color = el.dataset.color;
            if (bg) el.style.setProperty('background-color', bg, 'important');
            if (color) {
                el.style.setProperty('color', color, 'important');
                el.querySelectorAll('.plate-ind-text, .plate-number, .plate-category-label').forEach(child => {
                    child.style.setProperty('color', color, 'important');
                });
            }
        });
    };

    applyDynamicStyles();
});
