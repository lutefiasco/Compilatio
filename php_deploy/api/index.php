<?php
/**
 * Compilatio API
 *
 * Endpoints:
 *   GET /api/repositories          - List all repositories with counts
 *   GET /api/repositories/{id}     - Single repository with collections
 *   GET /api/manuscripts           - List manuscripts (with filtering)
 *   GET /api/manuscripts/{id}      - Single manuscript details
 *   GET /api/featured              - Random featured manuscript
 */

header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');

require_once __DIR__ . '/../includes/config.php';

// Get action from rewritten URL or query param
$action = $_GET['action'] ?? 'unknown';
$id = isset($_GET['id']) ? (int)$_GET['id'] : null;

try {
    $pdo = getDbConnection();

    switch ($action) {
        case 'repositories':
            echo json_encode(getRepositories($pdo));
            break;

        case 'repository':
            if (!$id) {
                http_response_code(400);
                echo json_encode(['error' => 'Repository ID required']);
                break;
            }
            $result = getRepository($pdo, $id);
            if (!$result) {
                http_response_code(404);
                echo json_encode(['error' => 'Repository not found']);
            } else {
                echo json_encode($result);
            }
            break;

        case 'manuscripts':
            echo json_encode(getManuscripts($pdo, $_GET));
            break;

        case 'manuscript':
            if (!$id) {
                http_response_code(400);
                echo json_encode(['error' => 'Manuscript ID required']);
                break;
            }
            $result = getManuscript($pdo, $id);
            if (!$result) {
                http_response_code(404);
                echo json_encode(['error' => 'Manuscript not found']);
            } else {
                echo json_encode($result);
            }
            break;

        case 'featured':
            $result = getFeatured($pdo);
            if (!$result) {
                http_response_code(404);
                echo json_encode(['error' => 'No manuscripts available']);
            } else {
                echo json_encode($result);
            }
            break;

        default:
            http_response_code(404);
            echo json_encode(['error' => 'Unknown endpoint']);
    }

} catch (PDOException $e) {
    http_response_code(500);
    echo json_encode(['error' => 'Database error']);
    // Log error for debugging (don't expose to client)
    error_log('Compilatio API Error: ' . $e->getMessage());
}

/**
 * List all repositories with manuscript counts
 */
function getRepositories(PDO $pdo): array {
    $stmt = $pdo->query("
        SELECT
            r.id, r.name, r.short_name, r.logo_url, r.catalogue_url,
            COUNT(m.id) as manuscript_count
        FROM repositories r
        LEFT JOIN manuscripts m ON m.repository_id = r.id
        GROUP BY r.id
        ORDER BY r.name
    ");
    return $stmt->fetchAll();
}

/**
 * Get single repository with its collections
 */
function getRepository(PDO $pdo, int $id): ?array {
    // Get repository
    $stmt = $pdo->prepare("SELECT * FROM repositories WHERE id = ?");
    $stmt->execute([$id]);
    $repo = $stmt->fetch();

    if (!$repo) {
        return null;
    }

    // Get collections with counts
    $stmt = $pdo->prepare("
        SELECT collection, COUNT(*) as count
        FROM manuscripts
        WHERE repository_id = ? AND collection IS NOT NULL
        GROUP BY collection
        ORDER BY collection
    ");
    $stmt->execute([$id]);

    $repo['collections'] = [];
    while ($row = $stmt->fetch()) {
        $repo['collections'][] = [
            'name' => $row['collection'],
            'count' => (int)$row['count']
        ];
    }

    return $repo;
}

/**
 * List manuscripts with optional filtering
 */
function getManuscripts(PDO $pdo, array $params): array {
    $repoId = isset($params['repository_id']) ? (int)$params['repository_id'] : null;
    $collection = $params['collection'] ?? null;
    $limit = min((int)($params['limit'] ?? 50), 200);
    $offset = (int)($params['offset'] ?? 0);

    // Build WHERE clause
    $where = [];
    $bindings = [];

    if ($repoId) {
        $where[] = 'm.repository_id = ?';
        $bindings[] = $repoId;
    }

    if ($collection !== null) {
        $where[] = 'm.collection = ?';
        $bindings[] = $collection;
    }

    $whereSQL = $where ? 'WHERE ' . implode(' AND ', $where) : '';

    // Get total count
    $countSQL = "SELECT COUNT(*) as total FROM manuscripts m $whereSQL";
    $stmt = $pdo->prepare($countSQL);
    $stmt->execute($bindings);
    $total = (int)$stmt->fetch()['total'];

    // Get manuscripts
    $sql = "
        SELECT
            m.id, m.shelfmark, m.collection, m.date_display,
            m.contents, m.thumbnail_url, m.iiif_manifest_url,
            r.short_name as repository
        FROM manuscripts m
        JOIN repositories r ON r.id = m.repository_id
        $whereSQL
        ORDER BY m.collection, m.shelfmark
        LIMIT ? OFFSET ?
    ";

    $stmt = $pdo->prepare($sql);
    $stmt->execute(array_merge($bindings, [$limit, $offset]));
    $manuscripts = $stmt->fetchAll();

    return [
        'total' => $total,
        'limit' => $limit,
        'offset' => $offset,
        'manuscripts' => $manuscripts
    ];
}

/**
 * Get single manuscript with full details
 */
function getManuscript(PDO $pdo, int $id): ?array {
    $stmt = $pdo->prepare("
        SELECT
            m.*,
            r.name as repository_name,
            r.short_name as repository_short,
            r.logo_url as repository_logo,
            r.catalogue_url as repository_catalogue
        FROM manuscripts m
        JOIN repositories r ON r.id = m.repository_id
        WHERE m.id = ?
    ");
    $stmt->execute([$id]);
    return $stmt->fetch() ?: null;
}

/**
 * Get a random featured manuscript
 */
function getFeatured(PDO $pdo): ?array {
    $stmt = $pdo->query("
        SELECT
            m.id, m.shelfmark, m.collection, m.date_display,
            m.contents, m.thumbnail_url, m.iiif_manifest_url,
            r.short_name as repository
        FROM manuscripts m
        JOIN repositories r ON r.id = m.repository_id
        WHERE m.thumbnail_url IS NOT NULL
        ORDER BY RAND()
        LIMIT 1
    ");
    return $stmt->fetch() ?: null;
}
