const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const parser = require('@babel/parser');
const traverse = require('@babel/traverse').default;
const generate = require('@babel/generator').default;
const t = require('@babel/types');

const HOOK_LIKE_NAMES = new Set([
    'useState',
    'useEffect',
    'useCallback',
    'useMemo',
    'useRef',
    'useLayoutEffect',
    'useReducer',
    'useContext',
    'useImperativeHandle',
    'useDebugValue',
    'useTransition',
    'useDeferredValue',
    'useLocation',
    'useNavigate',
    'useParams',
    'useSearchParams',
    'useNavigationType',
    'useTheme',
]);

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const VIEWS_PATH = 'web/frontend/src/views';
const THEME_MOON_DIR = path.join(REPO_ROOT, 'web/frontend/src/themes/moon/routes');
const THEME_OLD_DIR = path.join(REPO_ROOT, 'web/frontend/src/themes/oldreddit/routes');
const LOGIC_DIR = path.join(REPO_ROOT, 'web/frontend/src/logic');
const MOVED_LOGIC_HOOKS = new Set([
    'useBalance',
    'useFollowState',
    'usePendingAgents',
    'usePendingBlocks',
    'usePendingDeletes',
    'usePendingSends',
    'usePendingSubscribes',
    'useQuests',
    'useTabs',
    'useTxStatus',
]);

const PARSER_PLUGINS = [
    'jsx',
    'classProperties',
    'objectRestSpread',
    'optionalChaining',
    'nullishCoalescingOperator',
    'dynamicImport',
    'numericSeparator',
    'topLevelAwait',
];

function logDebug(message) {
    console.debug(`[extract-theme-logic] ${message}`);
}

function parseSource(source, fileName) {
    try {
        return parser.parse(source, {
            sourceType: 'module',
            plugins: PARSER_PLUGINS,
        });
    } catch (error) {
        throw new Error(`Failed to parse ${fileName}: ${error.message}`);
    }
}

function getViewFiles() {
    const output = execSync(`git show HEAD:${VIEWS_PATH}/`, { encoding: 'utf8' });
    return output
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line.endsWith('.js'));
}

function getRouteBaseName(fileName) {
    const base = fileName.replace(/\.js$/, '');
    return base.replace(/View$/, '');
}

function isStyledTag(tag) {
    if (t.isIdentifier(tag, { name: 'styled' })) return true;
    if (t.isMemberExpression(tag) && t.isIdentifier(tag.object, { name: 'styled' })) return true;
    if (t.isCallExpression(tag) && t.isIdentifier(tag.callee, { name: 'styled' })) return true;
    return false;
}

function isStyleHelperInit(init) {
    if (!init) return false;
    if (t.isTaggedTemplateExpression(init)) {
        if (isStyledTag(init.tag)) return true;
        if (t.isIdentifier(init.tag, { name: 'css' })) return true;
        if (t.isIdentifier(init.tag, { name: 'keyframes' })) return true;
    }
    return false;
}

function isStyledDeclaration(node) {
    if (!t.isVariableDeclaration(node)) return false;
    return node.declarations.some((decl) => isStyleHelperInit(decl.init));
}

function walkNode(node, visit, skipNestedFunctions = false) {
    if (!node) return;
    if (
        skipNestedFunctions &&
        (t.isFunctionDeclaration(node) ||
            t.isFunctionExpression(node) ||
            t.isArrowFunctionExpression(node))
    ) {
        return;
    }
    visit(node);
    const keys = t.VISITOR_KEYS[node.type] || [];
    for (const key of keys) {
        const value = node[key];
        if (Array.isArray(value)) {
            value.forEach((child) => walkNode(child, visit, skipNestedFunctions));
        } else {
            walkNode(value, visit, skipNestedFunctions);
        }
    }
}

function functionHasJsxReturn(fnNode) {
    if (t.isArrowFunctionExpression(fnNode) && !t.isBlockStatement(fnNode.body)) {
        return t.isJSXElement(fnNode.body) || t.isJSXFragment(fnNode.body);
    }
    if (!t.isBlockStatement(fnNode.body)) return false;
    let hasJsx = false;
    walkNode(
        fnNode.body,
        (node) => {
            if (!t.isReturnStatement(node)) return;
            const arg = node.argument;
            if (t.isJSXElement(arg) || t.isJSXFragment(arg)) {
                hasJsx = true;
            }
        },
        true
    );
    return hasJsx;
}

function functionUsesHooks(fnNode) {
    let usesHook = false;
    walkNode(
        fnNode.body,
        (node) => {
            if (!t.isCallExpression(node)) return;
            const callee = node.callee;
            if (t.isIdentifier(callee) && callee.name.startsWith('use')) {
                usesHook = true;
            }
            if (
                t.isMemberExpression(callee) &&
                t.isIdentifier(callee.object, { name: 'React' }) &&
                t.isIdentifier(callee.property) &&
                HOOK_LIKE_NAMES.has(callee.property.name)
            ) {
                usesHook = true;
            }
        },
        true
    );
    return usesHook;
}

function collectDeclaredNames(node) {
    const names = new Set();
    if (t.isVariableDeclaration(node)) {
        for (const decl of node.declarations) {
            collectPatternNames(decl.id, names);
        }
    }
    if (t.isFunctionDeclaration(node) && node.id) {
        names.add(node.id.name);
    }
    if (t.isClassDeclaration(node) && node.id) {
        names.add(node.id.name);
    }
    return names;
}

function collectPatternNames(pattern, names) {
    if (t.isIdentifier(pattern)) {
        names.add(pattern.name);
    } else if (t.isObjectPattern(pattern)) {
        for (const prop of pattern.properties) {
            if (t.isRestElement(prop)) {
                collectPatternNames(prop.argument, names);
            } else if (t.isObjectProperty(prop)) {
                collectPatternNames(prop.value, names);
            }
        }
    } else if (t.isArrayPattern(pattern)) {
        for (const elem of pattern.elements) {
            if (elem) collectPatternNames(elem, names);
        }
    } else if (t.isAssignmentPattern(pattern)) {
        collectPatternNames(pattern.left, names);
    }
}

function containsReturnOutsideNestedFunctions(statement) {
    let found = false;
    walkNode(
        statement,
        (node) => {
            if (t.isReturnStatement(node)) found = true;
        },
        true
    );
    return found;
}

function containsJsx(statement) {
    let found = false;
    walkNode(statement, (node) => {
        if (t.isJSXElement(node) || t.isJSXFragment(node)) {
            found = true;
        }
    });
    return found;
}

function buildHookCallArgument(param) {
    if (!param) return null;
    if (t.isIdentifier(param)) return param;
    if (t.isObjectPattern(param)) {
        const props = [];
        for (const prop of param.properties) {
            if (t.isRestElement(prop)) {
                props.push(t.spreadElement(prop.argument));
                continue;
            }
            if (t.isObjectProperty(prop)) {
                if (t.isIdentifier(prop.key) && t.isIdentifier(prop.value) && prop.key.name === prop.value.name) {
                    props.push(t.objectProperty(prop.key, prop.value, false, true));
                } else if (t.isIdentifier(prop.value)) {
                    props.push(t.objectProperty(prop.key, prop.value, prop.computed, false));
                } else if (t.isAssignmentPattern(prop.value) && t.isIdentifier(prop.value.left)) {
                    props.push(t.objectProperty(prop.key, prop.value.left, prop.computed, false));
                }
            }
        }
        return t.objectExpression(props);
    }
    return param;
}

function getReferencedIdentifiers(nodes) {
    const names = new Set();
    const program = t.file(t.program(nodes));
    traverse(program, {
        Identifier(path) {
            if (!path.isReferencedIdentifier()) return;
            names.add(path.node.name);
        },
        JSXIdentifier(path) {
            if (path.node.name[0] === path.node.name[0].toLowerCase()) return;
            names.add(path.node.name);
        },
    });
    return names;
}

function adjustImportSource(source, fromDir, toDir) {
    if (!source.startsWith('.')) return source;
    const absolute = path.resolve(fromDir, source);
    let relative = path.relative(toDir, absolute);
    if (!relative.startsWith('.')) relative = `./${relative}`;
    return relative.split(path.sep).join(path.posix.sep);
}

function adjustThemeImportSource(source, fromDir, themeDir) {
    if (!source.startsWith('.')) return source;
    const absolute = path.resolve(fromDir, source);
    const componentsDir = path.join(REPO_ROOT, 'web/frontend/src/components');
    const themeComponentsDir = path.join(REPO_ROOT, 'web/frontend/src/themes/moon/components');
    if (absolute.startsWith(componentsDir)) {
        const baseName = path.basename(absolute);
        const candidates = [
            path.join(themeComponentsDir, baseName),
            path.join(themeComponentsDir, `${baseName}.js`),
        ];
        const themeComponent = candidates.find((candidate) => fs.existsSync(candidate));
        if (themeComponent) {
            let relative = path.relative(themeDir, themeComponent);
            if (!relative.startsWith('.')) relative = `./${relative}`;
            return relative.split(path.sep).join(path.posix.sep);
        }
    }
    return adjustImportSource(source, fromDir, themeDir);
}

function adjustLogicImportSource(source, fromDir, logicDir) {
    if (!source.startsWith('.')) return source;
    const absolute = path.resolve(fromDir, source);
    const utilsDir = path.join(REPO_ROOT, 'web/frontend/src/utils');
    if (absolute.startsWith(utilsDir)) {
        const baseName = path.basename(absolute);
        const bareName = baseName.endsWith('.js') ? baseName.slice(0, -3) : baseName;
        if (MOVED_LOGIC_HOOKS.has(bareName)) {
            const hookPath = path.join(REPO_ROOT, 'web/frontend/src/logic', `${bareName}.js`);
            let relative = path.relative(logicDir, hookPath);
            if (!relative.startsWith('.')) relative = `./${relative}`;
            return relative.split(path.sep).join(path.posix.sep);
        }
    }
    return adjustImportSource(source, fromDir, logicDir);
}

function resolveImportUsage(ast) {
    const used = getReferencedIdentifiers(ast.program.body);
    const imports = [];
    for (const node of ast.program.body) {
        if (!t.isImportDeclaration(node)) continue;
        const specifiers = node.specifiers.filter((specifier) => used.has(specifier.local.name));
        if (specifiers.length === 0) continue;
        imports.push(
            t.importDeclaration(specifiers, t.stringLiteral(node.source.value))
        );
    }
    return imports;
}

function exportHelperNode(node) {
    if (t.isFunctionDeclaration(node) || t.isClassDeclaration(node) || t.isVariableDeclaration(node)) {
        return t.exportNamedDeclaration(node, []);
    }
    return node;
}

function findMainComponent(program, routeName) {
    let exportDecl = null;
    for (const node of program.body) {
        if (t.isExportDefaultDeclaration(node)) {
            exportDecl = node.declaration;
            break;
        }
    }
    if (exportDecl) {
        if (t.isFunctionDeclaration(exportDecl)) return { node: exportDecl, name: exportDecl.id?.name };
        if (t.isIdentifier(exportDecl)) {
            const name = exportDecl.name;
            for (const node of program.body) {
                if (t.isFunctionDeclaration(node) && node.id?.name === name) return { node, name };
                if (t.isVariableDeclaration(node)) {
                    for (const decl of node.declarations) {
                        if (t.isIdentifier(decl.id, { name })) return { node: decl.init, name };
                    }
                }
            }
        }
    }
    for (const node of program.body) {
        if (t.isFunctionDeclaration(node) && node.id?.name === routeName) return { node, name: routeName };
        if (t.isVariableDeclaration(node)) {
            for (const decl of node.declarations) {
                if (t.isIdentifier(decl.id, { name: routeName })) return { node: decl.init, name: routeName };
            }
        }
    }
    throw new Error(`Main component not found for ${routeName}`);
}

function transformComponent(fnNode, hookName, forceHook) {
    if (t.isArrowFunctionExpression(fnNode) && !t.isBlockStatement(fnNode.body)) {
        fnNode.body = t.blockStatement([t.returnStatement(fnNode.body)]);
    }
    if (!t.isBlockStatement(fnNode.body)) {
        throw new Error(`Component ${hookName} does not have a block body`);
    }

    const statements = fnNode.body.body;
    const movedStatements = [];
    const keptStatements = [];
    let hitReturnGate = false;
    for (const statement of statements) {
        if (hitReturnGate) {
            keptStatements.push(statement);
            continue;
        }
        if (containsReturnOutsideNestedFunctions(statement)) {
            keptStatements.push(statement);
            hitReturnGate = true;
            continue;
        }
        if (containsJsx(statement)) {
            keptStatements.push(statement);
            continue;
        }
        movedStatements.push(statement);
    }

    const declared = new Set();
    for (const statement of movedStatements) {
        for (const name of collectDeclaredNames(statement)) {
            declared.add(name);
        }
    }

    const usedInKept = getReferencedIdentifiers(keptStatements);
    const returnNames = Array.from(declared).filter((name) => usedInKept.has(name));

    const hookParam = fnNode.params[0] || null;
    const hookArgument = buildHookCallArgument(hookParam);

    const hookStatements = [...movedStatements];
    hookStatements.push(
        t.returnStatement(
            t.objectExpression(returnNames.map((name) => t.objectProperty(t.identifier(name), t.identifier(name), false, true)))
        )
    );

    const hookDeclaration = t.functionDeclaration(
        t.identifier(hookName),
        fnNode.params,
        t.blockStatement(hookStatements)
    );

    let hookCallStatement = null;
    if (returnNames.length > 0) {
        hookCallStatement = t.variableDeclaration('const', [
            t.variableDeclarator(
                t.objectPattern(returnNames.map((name) => t.objectProperty(t.identifier(name), t.identifier(name), false, true))),
                t.callExpression(t.identifier(hookName), hookArgument ? [hookArgument] : [])
            ),
        ]);
    } else if (forceHook) {
        hookCallStatement = t.expressionStatement(
            t.callExpression(t.identifier(hookName), hookArgument ? [hookArgument] : [])
        );
    }

    const newBodyStatements = hookCallStatement ? [hookCallStatement, ...keptStatements] : keptStatements;
    fnNode.body.body = newBodyStatements;

    return {
        hookDeclaration,
        hookName,
        movedStatements,
        returnNames,
    };
}

function processFile(fileName) {
    const routeName = fileName.replace(/\.js$/, '');
    const routeBase = getRouteBaseName(fileName);
    const hookBaseName = `use${routeBase}`;
    logDebug(`Processing ${routeName} -> ${hookBaseName}`);

    const source = execSync(`git show HEAD:${VIEWS_PATH}/${fileName}`, { encoding: 'utf8' });
    const ast = parseSource(source, fileName);

    const originalImports = ast.program.body.filter((node) => t.isImportDeclaration(node));
    const originalNonImports = ast.program.body.filter((node) => !t.isImportDeclaration(node));

    const mainComponent = findMainComponent(ast.program, routeName);

    const helperNodes = [];
    const themeNodes = [];
    for (const node of originalNonImports) {
        if (t.isExportDefaultDeclaration(node)) {
            themeNodes.push(node);
            continue;
        }
        if (isStyledDeclaration(node)) {
            themeNodes.push(node);
            continue;
        }
        if (t.isFunctionDeclaration(node) && functionHasJsxReturn(node)) {
            themeNodes.push(node);
            continue;
        }
        if (t.isVariableDeclaration(node)) {
            const hasJsx = node.declarations.some((decl) => {
                const init = decl.init;
                if (!init) return false;
                if (t.isArrowFunctionExpression(init) || t.isFunctionExpression(init)) {
                    return functionHasJsxReturn(init);
                }
                return false;
            });
            if (hasJsx) {
                themeNodes.push(node);
                continue;
            }
        }
        helperNodes.push(node);
    }

    const hookDeclarations = [];
    const hookNames = new Set();

    traverse(ast, {
        ExportDefaultDeclaration(path) {
            const decl = path.node.declaration;
            if (!t.isFunctionDeclaration(decl)) return;
            if (!functionHasJsxReturn(decl)) return;
            const isMain = decl.id?.name === mainComponent.name;
            const usesHooks = functionUsesHooks(decl) || isMain;
            if (!usesHooks) return;
            const hookName = isMain ? hookBaseName : `use${decl.id.name}`;
            if (hookNames.has(hookName)) throw new Error(`Duplicate hook name ${hookName} in ${routeName}`);
            const result = transformComponent(decl, hookName, true);
            hookDeclarations.push(result.hookDeclaration);
            hookNames.add(hookName);
        },
        FunctionDeclaration(path) {
            if (path.parent.type !== 'Program') return;
            if (!functionHasJsxReturn(path.node)) return;
            const isMain = path.node.id?.name === mainComponent.name;
            const usesHooks = functionUsesHooks(path.node) || isMain;
            if (!usesHooks) return;
            const hookName = isMain ? hookBaseName : `use${path.node.id.name}`;
            if (hookNames.has(hookName)) throw new Error(`Duplicate hook name ${hookName} in ${routeName}`);
            const result = transformComponent(path.node, hookName, true);
            hookDeclarations.push(result.hookDeclaration);
            hookNames.add(hookName);
        },
        VariableDeclarator(path) {
            if (path.parentPath.parent.type !== 'Program') return;
            const init = path.node.init;
            if (!init || !(t.isArrowFunctionExpression(init) || t.isFunctionExpression(init))) return;
            if (!functionHasJsxReturn(init)) return;
            const name = path.node.id.name;
            const isMain = name === mainComponent.name;
            const usesHooks = functionUsesHooks(init) || isMain;
            if (!usesHooks) return;
            const hookName = isMain ? hookBaseName : `use${name}`;
            if (hookNames.has(hookName)) throw new Error(`Duplicate hook name ${hookName} in ${routeName}`);
            const result = transformComponent(init, hookName, true);
            hookDeclarations.push(result.hookDeclaration);
            hookNames.add(hookName);
        },
    });

    const helperExports = helperNodes.map(exportHelperNode);
    const logicProgram = t.program([
        ...originalImports,
        ...helperExports,
        ...hookDeclarations.map((decl) => t.exportNamedDeclaration(decl, [])),
    ]);

    const themeProgram = t.program([
        ...originalImports,
        ...themeNodes,
    ]);

    const themeAst = { ...ast, program: themeProgram };
    const logicAst = { ...ast, program: logicProgram };

    const themeImports = resolveImportUsage(themeAst);
    const logicImports = resolveImportUsage(logicAst);

    const viewDir = path.dirname(path.join(REPO_ROOT, VIEWS_PATH, fileName));
    const themeDir = THEME_MOON_DIR;
    const logicDir = LOGIC_DIR;

    const adjustedThemeImports = themeImports.map((imp) => {
        const source = imp.source.value;
        const adjusted = adjustThemeImportSource(source, viewDir, themeDir);
        return t.importDeclaration(imp.specifiers, t.stringLiteral(adjusted));
    });

    const adjustedLogicImports = logicImports.map((imp) => {
        const source = imp.source.value;
        const adjusted = adjustLogicImportSource(source, viewDir, logicDir);
        return t.importDeclaration(imp.specifiers, t.stringLiteral(adjusted));
    });

    const hookImportSpecifiers = Array.from(hookNames).map((name) =>
        t.importSpecifier(t.identifier(name), t.identifier(name))
    );

    const helperExportNames = helperNodes
        .filter((node) => t.isFunctionDeclaration(node) || t.isVariableDeclaration(node) || t.isClassDeclaration(node))
        .flatMap((node) => Array.from(collectDeclaredNames(node)));

    const themeIdentifiers = getReferencedIdentifiers(themeNodes);
    const helperImports = helperExportNames.filter((name) => themeIdentifiers.has(name));

    const helperImportSpecifiers = helperImports.map((name) =>
        t.importSpecifier(t.identifier(name), t.identifier(name))
    );

    const logicImportSpecifiers = [...hookImportSpecifiers, ...helperImportSpecifiers];
    const logicImport = logicImportSpecifiers.length
        ? t.importDeclaration(
              logicImportSpecifiers,
              t.stringLiteral(`../../../logic/${hookBaseName}`)
          )
        : null;

    const finalThemeProgram = t.program([
        ...adjustedThemeImports,
        ...(logicImport ? [logicImport] : []),
        ...themeNodes,
    ]);

    const finalLogicProgram = t.program([
        ...adjustedLogicImports,
        ...helperExports,
        ...hookDeclarations.map((decl) => t.exportNamedDeclaration(decl, [])),
    ]);

    const themeCode = generate(finalThemeProgram, { retainLines: false }).code;
    const logicCode = generate(finalLogicProgram, { retainLines: false }).code;

    const moonPath = path.join(THEME_MOON_DIR, fileName);
    const oldPath = path.join(THEME_OLD_DIR, fileName);
    const logicPath = path.join(LOGIC_DIR, `${hookBaseName}.js`);

    fs.writeFileSync(moonPath, themeCode);
    fs.writeFileSync(oldPath, themeCode);
    fs.writeFileSync(logicPath, logicCode);
    logDebug(`Wrote ${moonPath}, ${oldPath}, ${logicPath}`);
}

function main() {
    const files = getViewFiles();
    logDebug(`Found ${files.length} view files`);
    for (const file of files) {
        processFile(file);
    }
}

main();
