// Main JavaScript file for common functionality

document.addEventListener('DOMContentLoaded', function() {
    // Highlight active navigation link based on current page
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.nav-link');
    
    navLinks.forEach(link => {
        const linkPath = new URL(link.href).pathname;
        if (currentPath === linkPath || (currentPath === '/' && linkPath.includes('inventory'))) {
            link.classList.add('active');
        }
    });
    
    console.log('Deej - Inventory Manager loaded');
});


