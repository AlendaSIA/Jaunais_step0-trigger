def run(ctx: dict):
    last_id = ctx.get("last_processed_id")
    ids = ctx.get("sales_ids_full") or ctx.get("sales_ids")

    if last_id is None:
        ctx["error"] = "Missing ctx.last_processed_id"
        return ctx
    if not ids:
        ctx["error"] = "Missing ctx.sales_ids"
        return ctx

    # ids var būt tikai pēdējie 20; ja gribi pilno sarakstu, nākamajā solī to uzlabosim
    ids_sorted = sorted(ids)
    next_id = None
    for i in ids_sorted:
        if i > last_id:
            next_id = i
            break

    ctx["next_document_id"] = next_id
    ctx["has_next_document"] = next_id is not None
    return ctx
