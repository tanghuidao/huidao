"""Fix alerts API 500 error - convert ORM objects to dicts."""
import sys
sys.path.insert(0, '/app')

filepath = '/app/app/routers/phase3.py'

with open(filepath, 'r') as f:
    content = f.read()

# Fix the list_alerts endpoint to serialize ORM objects
old_code = '''@router.get("/alerts")
def list_alerts(limit: int = 50, db: Session = Depends(get_db)):
    """Get all active alerts."""
    from app.services.alerts import get_active_alerts
    alerts = get_active_alerts(db, limit=limit)
    return {"alerts": alerts, "count": len(alerts)}'''

new_code = '''@router.get("/alerts")
def list_alerts(limit: int = 50, db: Session = Depends(get_db)):
    """Get all active alerts."""
    from app.services.alerts import get_active_alerts
    alerts = get_active_alerts(db, limit=limit)
    alert_dicts = []
    for a in alerts:
        alert_dicts.append({
            "id": a.id,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "title": a.title,
            "description": a.description,
            "status": a.status,
            "related_articles": a.related_articles,
            "related_entities": a.related_entities,
            "extra_data": a.extra_data,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
        })
    return {"alerts": alert_dicts, "count": len(alert_dicts)}'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open(filepath, 'w') as f:
        f.write(content)
    print("Fixed list_alerts endpoint to serialize ORM objects")
else:
    print("ERROR: Could not find the exact code block to replace")
    # Show what's actually there
    idx = content.find('list_alerts')
    if idx >= 0:
        print(f"Found at index {idx}")
        print(f"Context: ...{content[idx:idx+200]}...")
    else:
        print("list_alerts not found in file")
