/**
 * NebulaLab OS - Client-Side App Logic & WebSocket Bridge
 */

class NebulaLabClient {
    constructor(apiUrl = '') {
        this.apiUrl = apiUrl;
        this.ws = null;
        this.listeners = new Map();
    }

    async getOverview() {
        const res = await fetch(`${this.apiUrl}/api/overview`);
        return await res.json();
    }

    async getMachines() {
        const res = await fetch(`${this.apiUrl}/api/machines`);
        return await res.json();
    }

    async submitJob(jobPayload) {
        const res = await fetch(`${this.apiUrl}/api/jobs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(jobPayload)
        });
        return await res.json();
    }

    connectWebSocket(onMessage, onStatusChange) {
        const loc = window.location;
        const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${proto}//${loc.host}/ws`;

        this.ws = new WebSocket(wsUrl);
        this.ws.onopen = () => onStatusChange && onStatusChange(true);
        this.ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                onMessage && onMessage(msg);
            } catch (err) {}
        };
        this.ws.onclose = () => {
            onStatusChange && onStatusChange(false);
            setTimeout(() => this.connectWebSocket(onMessage, onStatusChange), 3000);
        };
    }
}

if (typeof window !== 'undefined') {
    window.NebulaLabClient = NebulaLabClient;
}
