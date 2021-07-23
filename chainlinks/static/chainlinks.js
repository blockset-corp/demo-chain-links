function serviceChainGraph(canvasId, data) {
    new Chart($(canvasId), {
        type: 'matrix',
        data: {
            datasets: [{
                data: data.dataset,
                borderWidth: 1,
                backgroundColor(context) {
                    const value = context.dataset.data[context.dataIndex].v;
                    if (((value || {}).status_bd) || ((value || {}).status_fl)) {
                        return 'rgba(255, 79, 148, 0.75)';
                    }
                    if ((value || {}).status_pd) {
                        return 'rgba(249, 165, 56, 0.75)';
                    }
                    if ((value || {}).missing) {
                        return 'rgba(5, 175, 242, 0.50)';
                    }
                    if ((value || {}).total) {
                        return 'rgba(5, 175, 242, 1.0)';
                    }
                    return 'rgba(255, 255, 255)';
                },
                width: ({chart}) => (chart.chartArea || {}).width / data.x_labels.length - 1,
                height: ({chart}) =>(chart.chartArea || {}).height / data.y_labels.length - 1
            }],
        },
        options: {
            animation: false,
            aspectRatio: 5,
            plugins: {
                legend: false,
                tooltip: {
                    callbacks: {
                        title() {
                            return '';
                        },
                        label(context) {
                            const value = context.dataset.data[context.dataIndex].v;
                            if (((value || {}).start) || ((value || {}).end)) {
                                labels = ['Heights: ' + value.start.toLocaleString() + ' - ' + value.end.toLocaleString()]
                                if ((value || {}).status_gd) {
                                    labels.push('# Validated: ' + value.status_gd.toLocaleString())
                                }
                                if ((value || {}).status_bd) {
                                    labels.push('# Corrupted: ' + value.status_bd.toLocaleString())
                                }
                                if ((value || {}).status_fl) {
                                    labels.push('# Failed: ' + value.status_fl.toLocaleString())
                                }
                                if ((value || {}).status_pd) {
                                    labels.push('# Checking: ' + value.status_pd.toLocaleString())
                                }
                                if ((value || {}).missing) {
                                    labels.push('# Pending: ' + value.missing.toLocaleString())
                                }
                                return labels;
                            }
                            return ['None']
                        }
                    }
                }
            },
            scales: {
                x: {
                    type: 'category',
                    labels: data.x_labels,
                    offset: true,
                    ticks: {
                        display: true
                    },
                    grid: {
                        display: false
                    },
                    title: {
                        display: true,
                        text: 'Range Offset'
                    }
                },
                y: {
                    type: 'category',
                    labels: data.y_labels,
                    offset: true,
                    ticks: {
                        display: true
                    },
                    grid: {
                        display: false
                    },
                    title: {
                        display: true,
                        text: 'Height Range'
                    }
                }
            }
        }
    });
}
