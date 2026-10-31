const fs = require('fs');
const path = require('path');

const rootDir = __dirname;
const distDir = path.join(rootDir, 'dist');

// Ensure dist directory exists
if (fs.existsSync(distDir)) {
    fs.rmSync(distDir, { recursive: true, force: true });
}
fs.mkdirSync(distDir, { recursive: true });
fs.mkdirSync(path.join(distDir, 'static'), { recursive: true });
fs.mkdirSync(path.join(distDir, 'dashboard'), { recursive: true });

// Copy static assets
function copyDir(src, dest) {
    fs.mkdirSync(dest, { recursive: true });
    for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
        const srcPath = path.join(src, entry.name);
        const destPath = path.join(dest, entry.name);
        if (entry.isDirectory()) {
            copyDir(srcPath, destPath);
        } else {
            fs.copyFileSync(srcPath, destPath);
        }
    }
}

const frontendStaticDir = path.join(rootDir, 'frontend', 'static');
copyDir(frontendStaticDir, path.join(distDir, 'static'));
// Also copy directly to root of dist for flexible path resolution
copyDir(frontendStaticDir, distDir);

// Process index.html template into static HTML
let indexHtml = fs.readFileSync(path.join(rootDir, 'frontend', 'templates', 'index.html'), 'utf8');

// Replace url_for('static', filename='...')
indexHtml = indexHtml.replace(/\{\{\s*url_for\('static',\s*filename='([^']+)'\)\s*\}\}/g, '/static/$1');
// Replace url_for('auth.google_login')
indexHtml = indexHtml.replace(/\{\{\s*url_for\('auth\.google_login'\)\s*\}\}/g, '/api/auth/google');
// Replace Jinja flash messages block
indexHtml = indexHtml.replace(/\{%\s*with\s+messages\s*=[^%]+%\}.*?\{%\s*endwith\s*%\}/gs, '<div class="flash-container" id="flash-container"></div>');

fs.writeFileSync(path.join(distDir, 'index.html'), indexHtml, 'utf8');

// Process dashboard.html template into static HTML
let dashboardHtml = fs.readFileSync(path.join(rootDir, 'frontend', 'templates', 'dashboard.html'), 'utf8');

dashboardHtml = dashboardHtml.replace(/\{\{\s*url_for\('static',\s*filename='([^']+)'\)\s*\}\}/g, '/static/$1');
dashboardHtml = dashboardHtml.replace(/\{\{\s*url_for\('auth\.google_login'\)\s*\}\}/g, '/api/auth/google');
dashboardHtml = dashboardHtml.replace(/\{%\s*with\s+messages\s*=[^%]+%\}.*?\{%\s*endwith\s*%\}/gs, '<div class="flash-container" id="flash-container"></div>');

fs.writeFileSync(path.join(distDir, 'dashboard.html'), dashboardHtml, 'utf8');
fs.writeFileSync(path.join(distDir, 'dashboard', 'index.html'), dashboardHtml, 'utf8');

// Create _headers for security & caching
const headersContent = `/*
  X-Frame-Options: SAMEORIGIN
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: document-domain=(), geolocation=(), microphone=()

/static/*
  Cache-Control: public, max-age=31536000, immutable
`;
fs.writeFileSync(path.join(distDir, '_headers'), headersContent, 'utf8');

console.log('Static frontend assets generated in dist/ successfully!');

