"""A fixed search scope, supplied from Zotero's current collection membership."""

def scope_fields(data):
    collection = data.get("collection_id", 0)
    if type(collection) is not int or collection < 0:
        raise ValueError("Ungültige Sammlung")
    if "attachment_keys" not in data:
        if collection:
            raise ValueError("Dateiauswahl der Sammlung fehlt")
        return {}
    keys = data["attachment_keys"]
    if (not isinstance(keys, list) or len(keys) > 100000 or
            any(not isinstance(key, str) or not 1 <= len(key) <= 64 for key in keys)):
        raise ValueError("Ungültige Dateiauswahl der Sammlung")
    # An explicit empty list means an empty collection, never the whole library.
    return {"collection_id": collection, "attachment_keys": sorted(set(keys))}


def scope_matches(saved, requested):
    if "collection_id" in requested and requested["collection_id"] != saved.get("collection_id", 0):
        return False
    if "attachment_keys" in requested:
        return scope_fields(requested).get("attachment_keys") == saved.get("attachment_keys")
    return True


def scoped_languages(engine, library_id, scope):
    if "attachment_keys" in scope:
        return engine.languages(library_id, attachment_keys=scope["attachment_keys"])
    return engine.languages(library_id)


def check_hit_scope(hit, scope):
    if "attachment_keys" in scope and hit.get("attachment_key") not in scope["attachment_keys"]:
        raise ValueError("Fundstelle gehört nicht zur gewählten Sammlung")
